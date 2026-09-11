"""Unit tests for ManagedSsoClientService."""

from unittest.mock import MagicMock

import pytest
from qontract_utils.keycloak_api import ManagedKeycloakClient
from qontract_utils.secret_reader import SecretNotFoundError

from qontract_api.cache.base import CacheBackend
from qontract_api.config import Settings
from qontract_api.integrations.managed_sso_client.domain import (
    KeycloakInstanceRef,
    ManagedSsoClientDesiredState,
    ManagedSsoClientManagementSecret,
    OidcDesiredState,
)
from qontract_api.integrations.managed_sso_client.keycloak_workspace_client import (
    KeycloakWorkspaceClient,
)
from qontract_api.integrations.managed_sso_client.schemas import (
    ManagedSsoClientActionCreate,
    ManagedSsoClientActionDelete,
    ManagedSsoClientActionMoveTenantSecret,
    ManagedSsoClientActionUpdate,
)
from qontract_api.integrations.managed_sso_client.service import (
    ManagedSsoClientService,
)
from qontract_api.models import Secret, TaskStatus


@pytest.fixture
def mock_settings() -> Settings:
    from qontract_api.config import SecretSettings, VaultSettings

    return Settings(
        secrets=SecretSettings(
            providers=[VaultSettings(url="https://vault.example.com")],
            default_provider_url="https://vault.example.com",
        ),
    )


@pytest.fixture
def mock_cache() -> MagicMock:
    return MagicMock(spec=CacheBackend)


@pytest.fixture
def mock_keycloak() -> MagicMock:
    return MagicMock(spec=KeycloakWorkspaceClient)


@pytest.fixture
def mock_workspace_client_factory(mock_keycloak: MagicMock) -> MagicMock:
    return MagicMock(
        return_value={
            "https://sso.example.com/auth/realms/redhat-external": mock_keycloak
        }
    )


@pytest.fixture
def mock_secret_manager() -> MagicMock:
    mock = MagicMock()
    mock.list.return_value = []
    return mock


@pytest.fixture
def service(
    mock_secret_manager: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
    mock_workspace_client_factory: MagicMock,
) -> ManagedSsoClientService:
    return ManagedSsoClientService(
        secret_manager=mock_secret_manager,
        cache=mock_cache,
        settings=mock_settings,
        workspace_client_factory=mock_workspace_client_factory,
    )


def _keycloak_instance() -> KeycloakInstanceRef:
    return KeycloakInstanceRef(
        url="https://sso.example.com/auth/realms/redhat-external",
        initial_access_token=Secret(
            secret_manager_url="https://vault.example.com",
            path="app-sre/keycloak/iat",
            field="token",
        ),
    )


def _desired(
    client_id: str = "my-app-ci-bot", **oidc_overrides: object
) -> ManagedSsoClientDesiredState:
    return ManagedSsoClientDesiredState(
        client_id=client_id,
        keycloak_instance=_keycloak_instance(),
        oidc=OidcDesiredState(
            redirect_uris=["https://example.com/callback"], **oidc_overrides
        ),
    )


def _management(
    client_id: str = "my-app-ci-bot", **overrides: object
) -> ManagedSsoClientManagementSecret:
    defaults: dict[str, object] = {
        "client_id": client_id,
        "client_secret": "s3cr3t",
        "registration_access_token": "reg-token",
        "issuer": "https://sso.example.com/auth/realms/redhat-external",
        # matches ManagedSsoClientSettings.default_output_vault_path_prefix's
        # real default - must stay in sync so tests that don't set `output`
        # don't spuriously trigger tenant-secret-path drift detection.
        "tenant_secret_path": (
            f"app-sre/integrations-throughput/managed-sso-client/output/{client_id}"
        ),
    }
    return ManagedSsoClientManagementSecret(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_reconcile_creates_new_client(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_secret_manager.list.return_value = []
    mock_keycloak.register_client.return_value = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        secret="s3cr3t",
        registration_access_token="reg-token",
        redirect_uris=["https://example.com/callback"],
    )

    result = service.reconcile([_desired()], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 1
    action = result.applied_actions[0]
    assert isinstance(action, ManagedSsoClientActionCreate)
    assert action.tenant_secret_path == (
        f"{mock_settings.managed_sso_client.default_output_vault_path_prefix}"
        "/my-app-ci-bot"
    )
    mock_keycloak.register_client.assert_called_once()
    # two writes: AppSRE-owned management secret + tenant-facing secret
    assert mock_secret_manager.write.call_count == 2


def test_create_succeeds_for_real_public_client(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    """A genuinely public client never gets a secret from Keycloak.

    That's expected, not a failure, and must not crash on write.
    """
    mock_secret_manager.list.return_value = []
    mock_keycloak.register_client.return_value = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        secret=None,
        public_client=True,
        registration_access_token="reg-token",
        redirect_uris=["https://example.com/callback"],
    )

    result = service.reconcile([_desired(access_type="public")], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 1
    written_data = [call.args[1] for call in mock_secret_manager.write.call_args_list]
    assert all("client_secret" not in data for data in written_data)


def test_create_still_raises_when_confidential_client_gets_no_secret(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    """A missing secret is still an error for a non-public client."""
    mock_secret_manager.list.return_value = []
    mock_keycloak.register_client.return_value = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        secret=None,
        public_client=False,
        registration_access_token="reg-token",
        redirect_uris=["https://example.com/callback"],
    )

    result = service.reconcile([_desired()], dry_run=False)

    assert result.status == TaskStatus.FAILED
    assert result.applied_count == 0
    assert "did not return a client_secret" in result.errors[0]


def test_create_rolls_back_keycloak_registration_on_vault_write_failure(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    mock_secret_manager.list.return_value = []
    mock_secret_manager.write.side_effect = RuntimeError("vault unreachable")
    mock_keycloak.register_client.return_value = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        secret="s3cr3t",
        registration_access_token="reg-token",
        redirect_uris=["https://example.com/callback"],
    )

    result = service.reconcile([_desired()], dry_run=False)

    assert result.status == TaskStatus.FAILED
    assert result.applied_count == 0
    mock_keycloak.delete_client.assert_called_once_with(
        client_id="my-app-ci-bot", registration_access_token="reg-token"
    )


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def test_reconcile_no_changes_produces_no_actions(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    desired = _desired()
    assert desired.oidc is not None
    mock_secret_manager.list.return_value = [desired.client_id]
    mock_secret_manager.read_all.return_value = _management(
        desired.client_id
    ).model_dump()
    mock_keycloak.get_client.return_value = desired.oidc.to_managed_keycloak_client(
        client_id=desired.client_id, enabled=desired.enabled
    )

    result = service.reconcile([desired], dry_run=True)

    assert result.actions == []
    assert result.status == TaskStatus.SUCCESS


def test_reconcile_detects_drift_and_updates(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    desired = _desired(web_origins=["https://new-origin.example.com"])
    mock_secret_manager.list.return_value = [desired.client_id]
    mock_secret_manager.read_all.return_value = _management(
        desired.client_id
    ).model_dump()
    # current state on Keycloak has no web_origins - drift detected
    mock_keycloak.get_client.return_value = ManagedKeycloakClient(
        client_id=desired.client_id,
        redirect_uris=["https://example.com/callback"],
    )
    mock_keycloak.update_client.return_value = ManagedKeycloakClient(
        client_id=desired.client_id,
        redirect_uris=["https://example.com/callback"],
        registration_access_token="new-reg-token",
    )

    result = service.reconcile([desired], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.applied_actions) == 1
    action = result.applied_actions[0]
    assert isinstance(action, ManagedSsoClientActionUpdate)
    mock_keycloak.update_client.assert_called_once()
    mock_secret_manager.write.assert_called_once()
    _written_path, written_data = mock_secret_manager.write.call_args.args
    assert written_data["registration_access_token"] == "new-reg-token"
    assert written_data["client_secret"] == "s3cr3t"  # unchanged by update


def test_update_token_persist_failure_raises_distinct_error(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    desired = _desired(web_origins=["https://new-origin.example.com"])
    mock_secret_manager.list.return_value = [desired.client_id]
    mock_secret_manager.read_all.return_value = _management(
        desired.client_id
    ).model_dump()
    mock_keycloak.get_client.return_value = ManagedKeycloakClient(
        client_id=desired.client_id, redirect_uris=["https://example.com/callback"]
    )
    mock_keycloak.update_client.return_value = ManagedKeycloakClient(
        client_id=desired.client_id,
        redirect_uris=["https://example.com/callback"],
        registration_access_token="new-reg-token",
    )
    mock_secret_manager.write.side_effect = RuntimeError("vault down")

    result = service.reconcile([desired], dry_run=False)

    assert result.status == TaskStatus.FAILED
    assert result.applied_count == 0
    assert any("INCONSISTENT" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Output path migration
# ---------------------------------------------------------------------------


def test_diff_detects_output_path_drift_even_when_keycloak_matches(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    """Changing `output` alone must not be a silent no-op."""
    custom_output = Secret(
        secret_manager_url="https://vault.example.com",
        path="app-interface/app-sre/glitchtip/dev",
    )
    desired = ManagedSsoClientDesiredState(
        client_id="my-app-ci-bot",
        keycloak_instance=_keycloak_instance(),
        oidc=OidcDesiredState(redirect_uris=["https://example.com/callback"]),
        output=custom_output,
    )
    mock_secret_manager.list.return_value = ["my-app-ci-bot"]
    mock_secret_manager.read_all.return_value = _management(
        "my-app-ci-bot"
    ).model_dump()
    # Keycloak-side config matches exactly - only output differs
    assert desired.oidc is not None
    mock_keycloak.get_client.return_value = desired.oidc.to_managed_keycloak_client(
        client_id=desired.client_id, enabled=desired.enabled
    )

    result = service.reconcile([desired], dry_run=True)

    assert len(result.actions) == 1
    action = result.actions[0]
    assert isinstance(action, ManagedSsoClientActionMoveTenantSecret)
    assert action.tenant_secret_path == "app-interface/app-sre/glitchtip/dev"


def test_update_moves_tenant_secret_without_touching_keycloak(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    """An output-path-only change must migrate the secret, not rotate Keycloak."""
    custom_output = Secret(
        secret_manager_url="https://vault.example.com",
        path="app-interface/app-sre/glitchtip/dev",
    )
    desired = ManagedSsoClientDesiredState(
        client_id="my-app-ci-bot",
        keycloak_instance=_keycloak_instance(),
        oidc=OidcDesiredState(redirect_uris=["https://example.com/callback"]),
        output=custom_output,
    )
    old_management = _management("my-app-ci-bot")
    mock_secret_manager.list.return_value = ["my-app-ci-bot"]
    mock_secret_manager.read_all.return_value = old_management.model_dump()
    assert desired.oidc is not None
    mock_keycloak.get_client.return_value = desired.oidc.to_managed_keycloak_client(
        client_id=desired.client_id, enabled=desired.enabled
    )

    result = service.reconcile([desired], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    mock_keycloak.update_client.assert_not_called()
    # get_client is called exactly once, during _diff_client - an
    # output-path-only update must not re-fetch or re-compare live state.
    mock_keycloak.get_client.assert_called_once()

    written = {
        call.args[0].path: call.args[1]
        for call in mock_secret_manager.write.call_args_list
    }
    assert written["app-interface/app-sre/glitchtip/dev"]["client_secret"] == "s3cr3t"
    management_writes = [d for d in written.values() if "tenant_secret_path" in d]
    assert len(management_writes) == 1
    assert management_writes[0]["tenant_secret_path"] == (
        "app-interface/app-sre/glitchtip/dev"
    )

    mock_secret_manager.delete.assert_called_once()
    deleted_secret = mock_secret_manager.delete.call_args.args[0]
    assert deleted_secret.path == old_management.tenant_secret_path


def test_update_moves_tenant_secret_and_updates_keycloak_when_both_changed(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
    mock_settings: Settings,
) -> None:
    """Output-path migration and Keycloak drift are independent - both can fire."""
    custom_output = Secret(
        secret_manager_url="https://vault.example.com",
        path="app-interface/app-sre/glitchtip/dev",
    )
    desired = ManagedSsoClientDesiredState(
        client_id="my-app-ci-bot",
        keycloak_instance=_keycloak_instance(),
        oidc=OidcDesiredState(
            redirect_uris=["https://example.com/callback"],
            web_origins=["https://new-origin.example.com"],
        ),
        output=custom_output,
    )
    old_management = _management("my-app-ci-bot")
    mock_secret_manager.list.return_value = ["my-app-ci-bot"]
    mock_secret_manager.read_all.return_value = old_management.model_dump()
    # current state on Keycloak has no web_origins - drift detected
    mock_keycloak.get_client.return_value = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
    )
    mock_keycloak.update_client.return_value = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
        registration_access_token="new-reg-token",
    )

    result = service.reconcile([desired], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    # two independent, explicit actions - the move always ordered before the update
    assert [type(a) for a in result.applied_actions] == [
        ManagedSsoClientActionMoveTenantSecret,
        ManagedSsoClientActionUpdate,
    ]
    mock_keycloak.update_client.assert_called_once()

    # exactly one write to the new tenant path (no accidental duplicate write)
    tenant_secret_writes = [
        call
        for call in mock_secret_manager.write.call_args_list
        if call.args[0].path == "app-interface/app-sre/glitchtip/dev"
    ]
    assert len(tenant_secret_writes) == 1
    assert tenant_secret_writes[0].args[1]["client_secret"] == "s3cr3t"

    written = {
        call.args[0].path: call.args[1]
        for call in mock_secret_manager.write.call_args_list
    }
    assert any(
        d.get("registration_access_token") == "new-reg-token" for d in written.values()
    )

    # the OLD tenant secret is deleted, not left behind and not overwritten
    mock_secret_manager.delete.assert_called_once()
    deleted_secret = mock_secret_manager.delete.call_args.args[0]
    assert deleted_secret.path == old_management.tenant_secret_path
    assert old_management.tenant_secret_path not in written

    # _update_client's own write (carrying the new token) must not revert the
    # tenant-secret-path migration that already happened via the move action.
    management_path = (
        f"{mock_settings.managed_sso_client.vault_path_prefix}/my-app-ci-bot"
    )
    assert written[management_path]["registration_access_token"] == "new-reg-token"
    assert written[management_path]["tenant_secret_path"] == (
        "app-interface/app-sre/glitchtip/dev"
    )


def test_move_tenant_secret_logs_but_does_not_raise_when_old_delete_fails(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    """A failed cleanup of the orphaned old secret must not fail the action."""
    custom_output = Secret(
        secret_manager_url="https://vault.example.com",
        path="app-interface/app-sre/glitchtip/dev",
    )
    desired = ManagedSsoClientDesiredState(
        client_id="my-app-ci-bot",
        keycloak_instance=_keycloak_instance(),
        oidc=OidcDesiredState(redirect_uris=["https://example.com/callback"]),
        output=custom_output,
    )
    mock_secret_manager.list.return_value = ["my-app-ci-bot"]
    mock_secret_manager.read_all.return_value = _management(
        "my-app-ci-bot"
    ).model_dump()
    mock_secret_manager.delete.side_effect = RuntimeError("vault down")
    assert desired.oidc is not None
    mock_keycloak.get_client.return_value = desired.oidc.to_managed_keycloak_client(
        client_id=desired.client_id, enabled=desired.enabled
    )

    result = service.reconcile([desired], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 1
    assert result.errors == []


def test_check_for_update_missing_management_secret_is_reported_as_error(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
) -> None:
    desired = _desired()
    mock_secret_manager.list.return_value = [desired.client_id]
    mock_secret_manager.read_all.side_effect = SecretNotFoundError

    result = service.reconcile([desired], dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert any(
        e.startswith(f"{desired.client_id}: expected an existing management secret")
        for e in result.errors
    )


def test_check_for_update_unresolvable_instance_error_is_prefixed_with_client_id(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
) -> None:
    # a keycloak_instance the mock_workspace_client_factory fixture never built
    other_instance = KeycloakInstanceRef(
        url="https://sso.example.com/auth/realms/other-realm",
        initial_access_token=Secret(
            secret_manager_url="https://vault.example.com",
            path="app-sre/keycloak/iat",
            field="token",
        ),
    )
    desired = ManagedSsoClientDesiredState(
        client_id="my-app-ci-bot",
        keycloak_instance=other_instance,
        oidc=OidcDesiredState(redirect_uris=["https://example.com/callback"]),
    )
    mock_secret_manager.list.return_value = [desired.client_id]
    mock_secret_manager.read_all.return_value = _management(
        desired.client_id
    ).model_dump()

    result = service.reconcile([desired], dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert any(
        e.startswith(f"{desired.client_id}: could not build a Keycloak client")
        for e in result.errors
    )


def test_check_for_update_fetch_failure_error_is_prefixed_with_client_id(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    """Every failure inside _check_for_update must be debuggable by client_id."""
    desired = _desired()
    mock_secret_manager.list.return_value = [desired.client_id]
    mock_secret_manager.read_all.return_value = _management(
        desired.client_id
    ).model_dump()
    mock_keycloak.get_client.side_effect = RuntimeError("keycloak unreachable")

    result = service.reconcile([desired], dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert any(
        e.startswith(f"{desired.client_id}: ") and "keycloak unreachable" in e
        for e in result.errors
    )


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_reconcile_deletes_client_absent_from_desired_state(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
    mock_settings: Settings,
) -> None:
    management = _management("my-app-old-bot")
    mock_secret_manager.list.return_value = ["my-app-old-bot"]
    mock_secret_manager.read_all.return_value = management.model_dump()

    result = service.reconcile([], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert isinstance(result.applied_actions[0], ManagedSsoClientActionDelete)
    mock_keycloak.delete_client.assert_called_once_with(
        client_id="my-app-old-bot", registration_access_token="reg-token"
    )
    deleted_paths = {
        call.args[0].path for call in mock_secret_manager.delete.call_args_list
    }
    expected_management_path = (
        f"{mock_settings.managed_sso_client.vault_path_prefix}/my-app-old-bot"
    )
    assert expected_management_path in deleted_paths
    assert management.tenant_secret_path in deleted_paths


def test_delete_treats_404_as_already_deleted(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    import httpx2

    management = _management("my-app-old-bot")
    mock_secret_manager.list.return_value = ["my-app-old-bot"]
    mock_secret_manager.read_all.return_value = management.model_dump()
    response = MagicMock()
    response.status_code = httpx2.codes.NOT_FOUND
    mock_keycloak.delete_client.side_effect = httpx2.HTTPStatusError(
        "not found", request=MagicMock(), response=response
    )

    result = service.reconcile([], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert mock_secret_manager.delete.call_count == 2


def test_delete_reraises_non_404_401_errors(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    import httpx2

    management = _management("my-app-old-bot")
    mock_secret_manager.list.return_value = ["my-app-old-bot"]
    mock_secret_manager.read_all.return_value = management.model_dump()
    response = MagicMock()
    response.status_code = httpx2.codes.INTERNAL_SERVER_ERROR
    mock_keycloak.delete_client.side_effect = httpx2.HTTPStatusError(
        "server error", request=MagicMock(), response=response
    )

    result = service.reconcile([], dry_run=False)

    assert result.status == TaskStatus.FAILED
    mock_secret_manager.delete.assert_not_called()


# ---------------------------------------------------------------------------
# Rename safety
# ---------------------------------------------------------------------------


def test_rename_produces_delete_old_and_create_new(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    """Renaming must not be special-cased - it should fall out naturally.

    The server has no concept of "rename" at all (client_id is opaque, taken
    as-is) - if the caller sends a different client_id than what's currently
    in Vault, that mechanically produces a delete of the old id plus a
    create of the new one, purely as a side effect of the Vault-key diff.
    """
    old_management = _management("my-app-old-name")
    mock_secret_manager.list.return_value = ["my-app-old-name"]
    mock_secret_manager.read_all.return_value = old_management.model_dump()
    mock_keycloak.register_client.return_value = ManagedKeycloakClient(
        client_id="my-app-new-name",
        secret="new-secret",
        registration_access_token="new-token",
        redirect_uris=["https://example.com/callback"],
    )

    renamed = _desired(client_id="my-app-new-name")
    result = service.reconcile([renamed], dry_run=True)

    action_types = {(a.action_type, a.client_id) for a in result.actions}
    assert ("delete", "my-app-old-name") in action_types
    assert ("create", "my-app-new-name") in action_types


# ---------------------------------------------------------------------------
# Custom output path
# ---------------------------------------------------------------------------


def test_output_path_used_when_set(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    custom_output = Secret(
        secret_manager_url="https://vault.example.com",
        path="my-app/creds/sso-client",
    )
    desired = ManagedSsoClientDesiredState(
        client_id="my-app-ci-bot",
        keycloak_instance=_keycloak_instance(),
        oidc=OidcDesiredState(redirect_uris=["https://example.com/callback"]),
        output=custom_output,
    )
    mock_secret_manager.list.return_value = []
    mock_keycloak.register_client.return_value = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        secret="s3cr3t",
        registration_access_token="reg-token",
        redirect_uris=["https://example.com/callback"],
    )

    result = service.reconcile([desired], dry_run=False)

    written_paths = {
        call.args[0].path for call in mock_secret_manager.write.call_args_list
    }
    assert "my-app/creds/sso-client" in written_paths
    action = result.applied_actions[0]
    assert isinstance(action, ManagedSsoClientActionCreate)
    assert action.tenant_secret_path == "my-app/creds/sso-client"


def test_default_output_path_used_when_not_set(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_secret_manager.list.return_value = []
    mock_keycloak.register_client.return_value = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        secret="s3cr3t",
        registration_access_token="reg-token",
        redirect_uris=["https://example.com/callback"],
    )

    service.reconcile([_desired()], dry_run=False)

    written_paths = {
        call.args[0].path for call in mock_secret_manager.write.call_args_list
    }
    expected = (
        f"{mock_settings.managed_sso_client.default_output_vault_path_prefix}"
        "/my-app-ci-bot"
    )
    assert expected in written_paths


def test_reconcile_reports_error_when_management_path_is_not_writable(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
    mock_settings: Settings,
) -> None:
    """A missing ACL on the AppSRE-owned management path must be caught.

    Caught in dry-run - before a Keycloak client is ever registered.
    """
    mock_secret_manager.list.return_value = []
    mock_secret_manager.can_write.return_value = False

    result = service.reconcile([_desired()], dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert not any(
        isinstance(action, ManagedSsoClientActionCreate) for action in result.actions
    )
    assert len(result.errors) == 1
    assert result.errors[0].startswith("my-app-ci-bot: ")
    assert (
        f"{mock_settings.managed_sso_client.vault_path_prefix}/my-app-ci-bot"
        in result.errors[0]
    )
    mock_keycloak.register_client.assert_not_called()
    # management is checked first - the tenant secret path is never reached
    mock_secret_manager.can_write.assert_called_once()


def test_reconcile_reports_error_when_output_path_is_not_writable(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    """A tenant-supplied output path with no Vault ACL must be caught.

    Caught in dry-run - before a Keycloak client is ever registered.
    """
    custom_output = Secret(
        secret_manager_url="https://vault.example.com",
        path="my-app/creds/sso-client",
    )
    desired = ManagedSsoClientDesiredState(
        client_id="my-app-ci-bot",
        keycloak_instance=_keycloak_instance(),
        oidc=OidcDesiredState(redirect_uris=["https://example.com/callback"]),
        output=custom_output,
    )
    mock_secret_manager.list.return_value = []
    # management path is writable, the tenant output path is not
    mock_secret_manager.can_write.side_effect = [True, False]

    result = service.reconcile([desired], dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert not any(
        isinstance(action, ManagedSsoClientActionCreate) for action in result.actions
    )
    assert len(result.errors) == 1
    assert result.errors[0].startswith("my-app-ci-bot: ")
    assert "my-app/creds/sso-client" in result.errors[0]
    mock_keycloak.register_client.assert_not_called()


def test_reconcile_checks_management_and_default_output_path_permission(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
    mock_settings: Settings,
) -> None:
    """Both the management secret and the default output path are checked.

    Never assume either is writable - it doesn't hurt to verify.
    """
    mock_secret_manager.list.return_value = []
    mock_keycloak.register_client.return_value = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        secret="s3cr3t",
        registration_access_token="reg-token",
        redirect_uris=["https://example.com/callback"],
    )

    service.reconcile([_desired()], dry_run=True)

    expected_management = Secret(
        secret_manager_url=mock_settings.secrets.default_provider_url,
        path=f"{mock_settings.managed_sso_client.vault_path_prefix}/my-app-ci-bot",
    )
    expected_output = Secret(
        secret_manager_url=mock_settings.secrets.default_provider_url,
        path=(
            f"{mock_settings.managed_sso_client.default_output_vault_path_prefix}"
            "/my-app-ci-bot"
        ),
    )
    assert mock_secret_manager.can_write.call_count == 2
    mock_secret_manager.can_write.assert_any_call(expected_management)
    mock_secret_manager.can_write.assert_any_call(expected_output)


def test_create_proceeds_when_output_path_is_writable(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    custom_output = Secret(
        secret_manager_url="https://vault.example.com",
        path="my-app/creds/sso-client",
    )
    desired = ManagedSsoClientDesiredState(
        client_id="my-app-ci-bot",
        keycloak_instance=_keycloak_instance(),
        oidc=OidcDesiredState(redirect_uris=["https://example.com/callback"]),
        output=custom_output,
    )
    mock_secret_manager.list.return_value = []
    mock_secret_manager.can_write.return_value = True
    mock_keycloak.register_client.return_value = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        secret="s3cr3t",
        registration_access_token="reg-token",
        redirect_uris=["https://example.com/callback"],
    )

    result = service.reconcile([desired], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 1
    assert mock_secret_manager.can_write.call_count == 2
    mock_secret_manager.can_write.assert_any_call(custom_output)


# ---------------------------------------------------------------------------
# Client cleanup
# ---------------------------------------------------------------------------


def test_keycloak_clients_are_closed_even_on_error(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak: MagicMock,
) -> None:
    mock_secret_manager.list.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        service.reconcile([_desired()], dry_run=True)

    mock_keycloak.close.assert_called_once()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_reconcile_exposes_managed_clients_gauge(
    service: ManagedSsoClientService,
    mock_secret_manager: MagicMock,
) -> None:
    from qontract_api.integrations.managed_sso_client.metrics import (
        INTEGRATION_NAME,
        managed_sso_clients_managed,
    )

    mock_secret_manager.list.return_value = ["client-1", "client-2", "client-3"]

    service.reconcile([_desired()], dry_run=True)

    assert managed_sso_clients_managed.labels(INTEGRATION_NAME)._value.get() == 3
