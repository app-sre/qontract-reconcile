"""Unit tests for SsoClientService."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import httpx2
import pytest
from jose import jwt
from qontract_utils.keycloak_api import KeycloakSsoClient

from qontract_api.cache.base import CacheBackend
from qontract_api.config import Settings
from qontract_api.integrations.sso_client.domain import (
    KeycloakInstanceSecret,
    SsoClientAuth,
    SsoClientCluster,
    SsoClientSecret,
)
from qontract_api.integrations.sso_client.schemas import (
    SsoClientActionCreate,
    SsoClientActionDelete,
)
from qontract_api.integrations.sso_client.service import SsoClientService
from qontract_api.models import Secret, TaskStatus

ISSUER_URL = "https://issuer.example.com"
KEYCLOAK_SECRET = KeycloakInstanceSecret(
    url=ISSUER_URL,
    secret=Secret(
        secret_manager_url="https://keycloak-vault.example.com",
        path="keycloak/instance1",
    ),
)
VAULT_TARGET = Secret(
    secret_manager_url="https://vault.example.com",
    path="rhidp/sso-client/prod",
)


def _iat(exp: int = 4102444800) -> str:
    return jwt.encode({"exp": exp}, "secret", algorithm="HS256")


def _iat_secret_data(exp: int = 4102444800) -> dict:
    """Real Vault secret shape for a Keycloak instance's IAT (no url field)."""
    return {
        "current_iat": {"id": "iat-id-1", "token": _iat(exp)},
        "previous_iat": "",
    }


def _stored_sso_client(**overrides: object) -> dict:
    """A full, valid SsoClientSecret.model_dump() - what's actually stored in Vault."""
    defaults = SsoClientSecret(
        client_id="obsolete-client",
        client_name="obsolete-client",
        client_secret="s3cr3t",
        redirect_uris=["https://console.example.com/oauth2callback/redhat-sso"],
        registration_access_token="rat",
        registration_client_uri=f"{ISSUER_URL}/clients-registrations/default/obsolete-client",
        issuer=ISSUER_URL,
    ).model_dump()
    return {**defaults, **overrides}


def _read_all_dispatch(sso_client_data: dict) -> object:
    """Build a read_all side_effect dispatching by secret path.

    The Keycloak instance secret resolves to the real IAT shape; any other path
    (SSO client delete lookups) resolves to sso_client_data.
    """

    def _dispatch(secret: Secret) -> dict:
        if secret.path == KEYCLOAK_SECRET.secret.path:
            return _iat_secret_data()
        return sso_client_data

    return _dispatch


def _cluster(
    name: str = "my-cluster",
    *,
    rhidp_enabled: bool = True,
    console_url: str | None = "https://console.example.com",
    group_filter_regex: str | None = None,
    org_id: str = "org-1",
) -> SsoClientCluster:
    return SsoClientCluster(
        name=name,
        organization_id=org_id,
        console_url=console_url,
        rhidp_enabled=rhidp_enabled,
        auth=SsoClientAuth(
            name="redhat-sso", issuer=ISSUER_URL, group_filter_regex=group_filter_regex
        ),
    )


@pytest.fixture
def mock_cache() -> MagicMock:
    m = MagicMock(spec=CacheBackend)
    m.lock.return_value.__enter__ = MagicMock()
    m.lock.return_value.__exit__ = MagicMock(return_value=False)
    return m


@pytest.fixture
def mock_secret_manager() -> MagicMock:
    m = MagicMock()
    m.list.return_value = []
    m.read_all.return_value = _iat_secret_data()
    return m


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def service(
    mock_cache: MagicMock, mock_secret_manager: MagicMock, settings: Settings
) -> SsoClientService:
    return SsoClientService(
        cache=mock_cache, secret_manager=mock_secret_manager, settings=settings
    )


@pytest.fixture
def mock_keycloak_instance() -> MagicMock:
    return MagicMock()


@pytest.fixture(autouse=True)
def patch_keycloak_instances(
    mock_keycloak_instance: MagicMock,
) -> Generator[MagicMock]:
    with patch(
        "qontract_api.integrations.sso_client.service.build_keycloak_instances",
        return_value={ISSUER_URL: mock_keycloak_instance},
    ) as mocked:
        yield mocked


def test_reconcile_no_changes(
    service: SsoClientService, mock_secret_manager: MagicMock
) -> None:
    cluster = _cluster()
    sso_client_id = "my-cluster-org-1-redhat-sso-issuer.example.com"
    mock_secret_manager.list.return_value = [sso_client_id]

    result = service.reconcile(
        "prod", [cluster], [KEYCLOAK_SECRET], VAULT_TARGET, dry_run=True
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []


def test_reconcile_creates_new_sso_client_dry_run(
    service: SsoClientService, mock_secret_manager: MagicMock
) -> None:
    mock_secret_manager.list.return_value = []

    result = service.reconcile(
        "prod", [_cluster()], [KEYCLOAK_SECRET], VAULT_TARGET, dry_run=True
    )

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], SsoClientActionCreate)
    assert result.applied_count == 0


def test_reconcile_ignores_disabled_clusters(
    service: SsoClientService, mock_secret_manager: MagicMock
) -> None:
    mock_secret_manager.list.return_value = []

    result = service.reconcile(
        "prod",
        [_cluster(rhidp_enabled=False)],
        [KEYCLOAK_SECRET],
        VAULT_TARGET,
        dry_run=True,
    )

    assert result.actions == []


def test_reconcile_create_executes_and_writes_secret(
    service: SsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak_instance: MagicMock,
) -> None:
    mock_secret_manager.list.return_value = []
    mock_keycloak_instance.register_client.return_value = KeycloakSsoClient(
        client_id="my-cluster-org-1-redhat-sso-issuer.example.com",
        client_secret="s3cr3t",
        redirect_uris=["https://console.example.com/oauth2callback/redhat-sso"],
        registration_access_token="rat",
        attributes={"what": "ever"},
    )

    result = service.reconcile(
        "prod",
        [_cluster(group_filter_regex="^team-.*$")],
        [KEYCLOAK_SECRET],
        VAULT_TARGET,
        dry_run=False,
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 1
    mock_keycloak_instance.register_client.assert_called_once()
    call_kwargs = mock_keycloak_instance.register_client.call_args.kwargs
    assert call_kwargs["group_filter_regex"] == "^team-.*$"

    mock_secret_manager.write.assert_called_once()
    written_secret, written_data = mock_secret_manager.write.call_args.args
    assert (
        written_secret.path
        == f"{VAULT_TARGET.path}/my-cluster-org-1-redhat-sso-issuer.example.com"
    )
    assert written_data["client_id"] == "my-cluster-org-1-redhat-sso-issuer.example.com"
    assert written_data["issuer"] == ISSUER_URL
    assert written_data["attributes"] == {"what": "ever"}
    assert written_data["registration_client_uri"] == (
        f"{ISSUER_URL}/clients-registrations/default/"
        "my-cluster-org-1-redhat-sso-issuer.example.com"
    )


def test_reconcile_create_skips_without_console_url(
    service: SsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak_instance: MagicMock,
) -> None:
    mock_secret_manager.list.return_value = []

    result = service.reconcile(
        "prod",
        [_cluster(console_url=None)],
        [KEYCLOAK_SECRET],
        VAULT_TARGET,
        dry_run=False,
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.errors == []
    assert result.applied_count == 0
    assert result.applied_actions == []
    mock_keycloak_instance.register_client.assert_not_called()
    mock_secret_manager.write.assert_not_called()


def test_reconcile_deletes_sso_client_dry_run(
    service: SsoClientService, mock_secret_manager: MagicMock
) -> None:
    mock_secret_manager.list.return_value = ["obsolete-client"]

    result = service.reconcile(
        "prod", [], [KEYCLOAK_SECRET], VAULT_TARGET, dry_run=True
    )

    assert len(result.actions) == 1
    assert isinstance(result.actions[0], SsoClientActionDelete)
    assert result.actions[0].sso_client_id == "obsolete-client"
    assert result.applied_count == 0


def test_reconcile_delete_executes_and_removes_secret(
    service: SsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak_instance: MagicMock,
) -> None:
    mock_secret_manager.list.return_value = ["obsolete-client"]
    mock_secret_manager.read_all.side_effect = _read_all_dispatch(_stored_sso_client())

    result = service.reconcile(
        "prod", [], [KEYCLOAK_SECRET], VAULT_TARGET, dry_run=False
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 1
    mock_keycloak_instance.delete_client.assert_called_once_with(
        client_id="obsolete-client", registration_access_token="rat"
    )
    delete_call = mock_secret_manager.delete.call_args
    assert delete_call.args[0].path == f"{VAULT_TARGET.path}/obsolete-client"


def test_reconcile_delete_swallows_401(
    service: SsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak_instance: MagicMock,
) -> None:
    mock_secret_manager.list.return_value = ["obsolete-client"]
    mock_secret_manager.read_all.side_effect = _read_all_dispatch(_stored_sso_client())
    response = MagicMock(status_code=401)
    mock_keycloak_instance.delete_client.side_effect = httpx2.HTTPStatusError(
        "unauthorized", request=MagicMock(), response=response
    )

    result = service.reconcile(
        "prod", [], [KEYCLOAK_SECRET], VAULT_TARGET, dry_run=False
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.errors == []
    assert result.applied_count == 1
    mock_secret_manager.delete.assert_called_once()


def test_reconcile_delete_reraises_non_401_as_error(
    service: SsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak_instance: MagicMock,
) -> None:
    mock_secret_manager.list.return_value = ["obsolete-client"]
    mock_secret_manager.read_all.side_effect = _read_all_dispatch(_stored_sso_client())
    response = MagicMock(status_code=500)
    mock_keycloak_instance.delete_client.side_effect = httpx2.HTTPStatusError(
        "server error", request=MagicMock(), response=response
    )

    result = service.reconcile(
        "prod", [], [KEYCLOAK_SECRET], VAULT_TARGET, dry_run=False
    )

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) == 1
    assert result.applied_count == 0
    mock_secret_manager.delete.assert_not_called()


def test_reconcile_per_action_error_isolation(
    service: SsoClientService,
    mock_secret_manager: MagicMock,
    mock_keycloak_instance: MagicMock,
) -> None:
    """One failing action must not prevent other actions from being applied."""
    mock_secret_manager.list.return_value = ["obsolete-client"]
    mock_secret_manager.read_all.side_effect = _read_all_dispatch(_stored_sso_client())
    mock_keycloak_instance.delete_client.side_effect = RuntimeError("boom")
    mock_keycloak_instance.register_client.return_value = KeycloakSsoClient(
        client_id="my-cluster-org-1-redhat-sso-issuer.example.com",
        client_secret="s3cr3t",
        redirect_uris=["https://console.example.com/oauth2callback/redhat-sso"],
        registration_access_token="rat",
        attributes={"what": "ever"},
    )

    result = service.reconcile(
        "prod", [_cluster()], [KEYCLOAK_SECRET], VAULT_TARGET, dry_run=False
    )

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) == 1
    assert "boom" in result.errors[0]
    assert result.applied_count == 1
    assert isinstance(result.applied_actions[0], SsoClientActionCreate)


def test_reconcile_deterministic_ordering(
    service: SsoClientService, mock_secret_manager: MagicMock
) -> None:
    mock_secret_manager.list.return_value = ["z-existing", "a-existing"]
    clusters = [_cluster("z-cluster"), _cluster("a-cluster")]

    result = service.reconcile(
        "prod", clusters, [KEYCLOAK_SECRET], VAULT_TARGET, dry_run=True
    )

    deletes = [a for a in result.actions if isinstance(a, SsoClientActionDelete)]
    creates = [a for a in result.actions if isinstance(a, SsoClientActionCreate)]
    assert [d.sso_client_id for d in deletes] == sorted(
        d.sso_client_id for d in deletes
    )
    assert [c.sso_client_id for c in creates] == sorted(
        c.sso_client_id for c in creates
    )


def test_reconcile_exposes_metrics(
    service: SsoClientService, mock_secret_manager: MagicMock
) -> None:
    from qontract_api.integrations.sso_client.metrics import (
        rhidp_managed_clusters,
        rhidp_sso_client_inital_access_token_expiration,
        rhidp_sso_client_number_of_clients,
        rhidp_sso_client_reconciled,
    )

    ocm_environment = "test-env-metrics"
    mock_secret_manager.list.return_value = []
    mock_secret_manager.read_all.return_value = _iat_secret_data(exp=1234567890)

    service.reconcile(
        ocm_environment,
        [_cluster(org_id="metrics-org")],
        [KEYCLOAK_SECRET],
        VAULT_TARGET,
        dry_run=True,
    )

    assert (
        rhidp_managed_clusters.labels(
            "rhidp-sso-client", ocm_environment, "metrics-org"
        )._value.get()
        == 1
    )
    assert (
        rhidp_sso_client_number_of_clients.labels(
            "rhidp-sso-client", ocm_environment
        )._value.get()
        == 0
    )
    assert (
        rhidp_sso_client_inital_access_token_expiration.labels(
            "rhidp-sso-client", ocm_environment, KEYCLOAK_SECRET.secret.path
        )._value.get()
        == 1234567890
    )
    assert (
        rhidp_sso_client_reconciled.labels(
            "rhidp-sso-client", ocm_environment
        )._value.get()
        == 1
    )
