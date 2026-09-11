"""Tests for the managed-sso-client client-side integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qontract_api_client.schemas import (
    ManagedSsoClientTaskResponse,
    ManagedSsoClientTaskResult,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.managed_sso_client.managed_sso_client import (
    AppV1,
    KeycloakInstanceV1,
    ManagedSsoClientOidcV1,
    ManagedSsoClientOpenidConnectV1,
    ManagedSsoClientV1,
)
from reconcile.managed_sso_client.integration import (
    ManagedSsoClientIntegration,
    ManagedSsoClientIntegrationParams,
)

SECRET_MANAGER_URL = "https://vault.example.com"


class _TestableIntegration(ManagedSsoClientIntegration):
    @property
    def secret_manager_url(self) -> str:
        return SECRET_MANAGER_URL


def _make_integration() -> _TestableIntegration:
    return _TestableIntegration(ManagedSsoClientIntegrationParams())


def _make_oidc(**overrides: object) -> ManagedSsoClientOidcV1:
    defaults: dict[str, object] = {
        "accessType": None,
        "directAccessGrantsEnabled": None,
        "serviceAccountsEnabled": None,
        "redirectUris": ["https://example.com/callback"],
        "postLogoutRedirectUris": None,
        "webOrigins": None,
        "consentRequired": None,
        "fullScopeAllowed": None,
        "defaultClientScopes": None,
        "optionalClientScopes": None,
    }
    return ManagedSsoClientOidcV1(**{**defaults, **overrides})


def _make_keycloak_instance() -> KeycloakInstanceV1:
    return KeycloakInstanceV1(
        url="https://sso.example.com/auth/realms/example-realm",
        initialAccessToken=VaultSecret(
            url=None,
            path="app-sre/keycloak/iat",
            field="token",
            version=None,
            format=None,
        ),
    )


def _make_client(
    name: str = "ci-bot",
    app_name: str = "my-app",
    output: str | None = None,
    enabled: bool | None = True,
    **oidc_overrides: object,
) -> ManagedSsoClientOpenidConnectV1:
    return ManagedSsoClientOpenidConnectV1(
        name=name,
        description="test client",
        enabled=enabled,
        app=AppV1(name=app_name),
        protocol="openid-connect",
        keycloakInstance=_make_keycloak_instance(),
        oidc=_make_oidc(**oidc_overrides),
        output=output,
    )


def _make_unresolved_protocol_client(
    name: str = "ci-bot", app_name: str = "my-app", protocol: str = "saml"
) -> ManagedSsoClientV1:
    """A client whose protocol doesn't resolve to any known concrete type.

    Simulates a client/server schema version skew - the schema itself only
    allows `openid-connect` today, so this can't happen via normal data, but
    compile_desired_state must still handle it defensively.
    """
    return ManagedSsoClientV1(
        name=name,
        description="test client",
        enabled=True,
        app=AppV1(name=app_name),
        protocol=protocol,
        keycloakInstance=_make_keycloak_instance(),
        output=None,
    )


# ---------------------------------------------------------------------------
# compile_desired_state
# ---------------------------------------------------------------------------


def test_compile_desired_state_maps_basic_fields() -> None:
    integration = _make_integration()
    client = _make_client()

    result = integration.compile_desired_state([client])

    assert len(result) == 1
    desired = result[0]
    assert desired.client_id == "my-app-ci-bot"
    assert (
        desired.keycloak_instance.url
        == "https://sso.example.com/auth/realms/example-realm"
    )
    assert desired.keycloak_instance.initial_access_token.secret_manager_url == (
        SECRET_MANAGER_URL
    )
    assert desired.oidc is not None
    assert desired.oidc.redirect_uris == ["https://example.com/callback"]


def test_compile_desired_state_defaults_enabled_to_true_when_unset() -> None:
    integration = _make_integration()
    client = _make_client(enabled=None)

    result = integration.compile_desired_state([client])

    assert result[0].enabled is True


def test_compile_desired_state_passes_through_enabled_false() -> None:
    integration = _make_integration()
    client = _make_client(enabled=False)

    result = integration.compile_desired_state([client])

    assert result[0].enabled is False


def test_compile_desired_state_passes_through_unset_access_type_as_none() -> None:
    """Unset accessType means "don't manage the client type", not "confidential".

    Resolving it to a concrete value here would mean actively asserting
    "confidential" on every create/update, including overriding a manual
    change made directly in Keycloak.
    """
    integration = _make_integration()
    client = _make_client(accessType=None)

    result = integration.compile_desired_state([client])

    assert result[0].oidc is not None
    assert result[0].oidc.access_type is None


def test_compile_desired_state_passes_through_unset_oidc_lists_as_none() -> None:
    """Unset (null) means "don't manage this field", not "empty".

    App-Interface/GraphQL returns null for an optional array that was never
    set. The server treats None as "not managed" (Keycloak's PUT merges by
    field and leaves it untouched) - coercing it to [] here would instead
    actively clear whatever Keycloak currently has for that field.
    """
    integration = _make_integration()
    client = _make_client(
        postLogoutRedirectUris=None,
        webOrigins=None,
        defaultClientScopes=None,
        optionalClientScopes=None,
    )

    result = integration.compile_desired_state([client])

    oidc = result[0].oidc
    assert oidc is not None
    assert oidc.post_logout_redirect_uris is None
    assert oidc.web_origins is None
    assert oidc.default_client_scopes is None
    assert oidc.optional_client_scopes is None


def test_compile_desired_state_rejects_unresolved_protocol() -> None:
    integration = _make_integration()
    client = _make_unresolved_protocol_client(protocol="saml")

    with pytest.raises(IntegrationError, match="unsupported protocol"):
        integration.compile_desired_state([client])


def test_compile_desired_state_output_none_when_unset() -> None:
    integration = _make_integration()
    client = _make_client(output=None)

    result = integration.compile_desired_state([client])

    assert result[0].output is None


def test_compile_desired_state_output_set_from_path() -> None:
    integration = _make_integration()
    client = _make_client(output="my-app/creds/sso-client")

    result = integration.compile_desired_state([client])

    assert result[0].output is not None
    assert result[0].output.path == "my-app/creds/sso-client"
    assert result[0].output.secret_manager_url == SECRET_MANAGER_URL


# ---------------------------------------------------------------------------
# reconcile()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_sends_request_and_returns_response() -> None:
    integration = _make_integration()
    desired = integration.compile_desired_state([_make_client()])
    fake_response = ManagedSsoClientTaskResponse(
        id="task-123",
        status=TaskStatus.PENDING,
        status_url="/api/v1/integrations/managed-sso-client/reconcile/task-123",
    )

    with patch(
        "reconcile.managed_sso_client.integration.reconcile_managed_sso_client",
        new_callable=AsyncMock,
        return_value=fake_response,
    ) as mock_reconcile:
        response = await integration.reconcile(desired_clients=desired, dry_run=True)

    mock_reconcile.assert_awaited_once()
    called_request = mock_reconcile.call_args[0][0]
    assert called_request.dry_run is True
    assert len(called_request.desired_clients) == 1
    assert response.id == "task-123"


# ---------------------------------------------------------------------------
# async_run()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_run_no_desired_state_exits_early() -> None:
    integration = _make_integration()

    with (
        patch("reconcile.managed_sso_client.integration.gql") as mock_gql,
        patch.object(integration, "get_managed_sso_clients", return_value=[]),
        patch(
            "reconcile.managed_sso_client.integration.reconcile_managed_sso_client",
            new_callable=AsyncMock,
        ) as mock_reconcile,
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=True)

    mock_reconcile.assert_not_called()


@pytest.mark.asyncio
async def test_async_run_dry_run_polls_and_raises_on_errors() -> None:
    integration = _make_integration()
    client = _make_client()
    fake_response = ManagedSsoClientTaskResponse(
        id="task-abc",
        status=TaskStatus.PENDING,
        status_url="/api/v1/integrations/managed-sso-client/reconcile/task-abc",
    )
    fake_result = ManagedSsoClientTaskResult(
        status=TaskStatus.FAILED,
        actions=[],
        applied_count=0,
        applied_actions=[],
        errors=["my-app-ci-bot: boom"],
    )

    with (
        patch("reconcile.managed_sso_client.integration.gql") as mock_gql,
        patch.object(integration, "get_managed_sso_clients", return_value=[client]),
        patch(
            "reconcile.managed_sso_client.integration.reconcile_managed_sso_client",
            new_callable=AsyncMock,
            return_value=fake_response,
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new_callable=AsyncMock,
            return_value=fake_result,
        ) as mock_poll,
        pytest.raises(IntegrationError, match="boom"),
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=True)

    mock_reconcile.assert_awaited_once()
    mock_poll.assert_awaited_once_with(
        status_url=fake_response.status_url,
        result_type=ManagedSsoClientTaskResult,
    )


@pytest.mark.asyncio
async def test_async_run_non_dry_run_does_not_poll() -> None:
    integration = _make_integration()
    client = _make_client()
    fake_response = ManagedSsoClientTaskResponse(
        id="task-xyz",
        status=TaskStatus.PENDING,
        status_url="/api/v1/integrations/managed-sso-client/reconcile/task-xyz",
    )

    with (
        patch("reconcile.managed_sso_client.integration.gql") as mock_gql,
        patch.object(integration, "get_managed_sso_clients", return_value=[client]),
        patch(
            "reconcile.managed_sso_client.integration.reconcile_managed_sso_client",
            new_callable=AsyncMock,
            return_value=fake_response,
        ),
        patch.object(
            integration, "poll_task_status", new_callable=AsyncMock
        ) as mock_poll,
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=False)

    mock_poll.assert_not_called()
