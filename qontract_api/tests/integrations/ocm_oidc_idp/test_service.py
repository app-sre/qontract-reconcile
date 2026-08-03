"""Unit tests for OcmOidcIdpService."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.ocm_api import OcmIdentityProvider, OcmIdentityProviderOidc
from qontract_utils.ocm_api.models import (
    OcmIdentityProviderOidcOpenId,
    OcmIdentityProviderOidcOpenIdClaims,
)

from qontract_api.cache.base import CacheBackend
from qontract_api.config import Settings
from qontract_api.external.ocm.schemas import OcmConnectionParams
from qontract_api.integrations.ocm_oidc_idp.domain import (
    OcmOidcIdpAuth,
    OcmOidcIdpCluster,
)
from qontract_api.integrations.ocm_oidc_idp.metrics import (
    rhidp_ocm_oidc_idp_reconcile_errors,
)
from qontract_api.integrations.ocm_oidc_idp.service import OcmOidcIdpService, _IdpState
from qontract_api.models import Secret, TaskStatus
from qontract_api.rhidp.domain import SsoClientSecret
from qontract_api.rhidp.metrics import rhidp_managed_clusters

ISSUER_URL = "https://issuer.example.com"
VAULT_TARGET = Secret(
    secret_manager_url="https://vault.example.com", path="rhidp/sso-client/prod"
)
OCM_CONNECTION = OcmConnectionParams(
    secret_manager_url="https://vault.example.com",
    path="ocm/prod",
    ocm_url="https://api.openshift.com",
    access_token_url="https://sso.redhat.com/token",
    access_token_client_id="client-id",
)


def _cluster(
    name: str = "my-cluster",
    *,
    org_id: str = "org-1",
    cluster_id: str = "cluster-1",
    oidc_enabled: bool = True,
    enforced: bool = False,
    group_filter_regex: str | None = None,
    auth_name: str = "redhat-sso",
    issuer: str = ISSUER_URL,
) -> OcmOidcIdpCluster:
    return OcmOidcIdpCluster(
        cluster_id=cluster_id,
        name=name,
        organization_id=org_id,
        auth=OcmOidcIdpAuth(
            name=auth_name,
            issuer=issuer,
            group_filter_regex=group_filter_regex,
            oidc_enabled=oidc_enabled,
            enforced=enforced,
        ),
    )


def _stored_secret(cluster: OcmOidcIdpCluster, **overrides: object) -> dict:
    """A full, valid SsoClientSecret.model_dump() - what sso_client wrote to Vault."""
    defaults = SsoClientSecret(
        client_id="client-1",
        client_name="client-1",
        client_secret="s3cr3t",
        redirect_uris=["https://console.example.com/oauth2callback/redhat-sso"],
        registration_access_token="rat",
        registration_client_uri=(
            f"{cluster.auth.issuer}/clients-registrations/default/client-1"
        ),
        issuer=cluster.auth.issuer,
    ).model_dump()
    return {**defaults, **overrides}


def _current_oidc_idp(
    idp_id: str = "idp-1", name: str = "redhat-sso", groups: list[str] | None = None
) -> OcmIdentityProviderOidc:
    """An IDP as returned by OCM: client_secret is never present on read."""
    return OcmIdentityProviderOidc(
        name=name,
        id=idp_id,
        open_id=OcmIdentityProviderOidcOpenId(
            client_id="client-1",
            client_secret=None,
            issuer=ISSUER_URL,
            claims=OcmIdentityProviderOidcOpenIdClaims(groups=groups or []),
        ),
    )


@pytest.fixture
def mock_cache() -> MagicMock:
    return MagicMock(spec=CacheBackend)


@pytest.fixture
def mock_secret_manager() -> MagicMock:
    m = MagicMock()
    m.read_all.return_value = {}
    return m


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def mock_workspace_client() -> MagicMock:
    m = MagicMock()
    m.get_identity_providers.return_value = []
    return m


@pytest.fixture(autouse=True)
def patch_workspace_client_factory(
    mock_workspace_client: MagicMock,
) -> Generator[MagicMock]:
    with patch(
        "qontract_api.integrations.ocm_oidc_idp.service.create_ocm_workspace_client",
        return_value=mock_workspace_client,
    ) as mocked:
        yield mocked


@pytest.fixture
def service(
    mock_cache: MagicMock, mock_secret_manager: MagicMock, settings: Settings
) -> OcmOidcIdpService:
    return OcmOidcIdpService(
        cache=mock_cache, secret_manager=mock_secret_manager, settings=settings
    )


def test_reconcile_no_op_when_no_clusters(service: OcmOidcIdpService) -> None:
    result = service.reconcile("prod", OCM_CONNECTION, [], VAULT_TARGET, dry_run=True)
    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []


def test_reconcile_no_changes(
    service: OcmOidcIdpService,
    mock_secret_manager: MagicMock,
    mock_workspace_client: MagicMock,
) -> None:
    cluster = _cluster()
    mock_secret_manager.read_all.return_value = _stored_secret(cluster)
    mock_workspace_client.get_identity_providers.return_value = [_current_oidc_idp()]

    result = service.reconcile(
        "prod", OCM_CONNECTION, [cluster], VAULT_TARGET, dry_run=True
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []


def test_reconcile_creates_new_idp_dry_run(
    service: OcmOidcIdpService,
    mock_secret_manager: MagicMock,
    mock_workspace_client: MagicMock,
) -> None:
    cluster = _cluster()
    mock_secret_manager.read_all.return_value = _stored_secret(cluster)

    result = service.reconcile(
        "prod", OCM_CONNECTION, [cluster], VAULT_TARGET, dry_run=True
    )

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert result.actions[0].action_type == "create"
    assert result.applied_actions == []
    mock_workspace_client.create_identity_provider.assert_not_called()


def test_reconcile_create_executes_when_not_dry_run(
    service: OcmOidcIdpService,
    mock_secret_manager: MagicMock,
    mock_workspace_client: MagicMock,
) -> None:
    cluster = _cluster()
    mock_secret_manager.read_all.return_value = _stored_secret(cluster)

    result = service.reconcile(
        "prod", OCM_CONNECTION, [cluster], VAULT_TARGET, dry_run=False
    )

    assert result.status == TaskStatus.SUCCESS
    assert len(result.applied_actions) == 1
    mock_workspace_client.create_identity_provider.assert_called_once()
    assert mock_workspace_client.create_identity_provider.call_args[0][0] == (
        cluster.cluster_id
    )


def test_reconcile_update_action_on_claims_change(
    service: OcmOidcIdpService,
    mock_secret_manager: MagicMock,
    mock_workspace_client: MagicMock,
) -> None:
    cluster = _cluster(group_filter_regex="^ai-.*")
    mock_secret_manager.read_all.return_value = _stored_secret(
        cluster, attributes={"group-filter-regex": "^ai-.*"}
    )
    mock_workspace_client.get_identity_providers.return_value = [
        _current_oidc_idp(idp_id="idp-1", groups=[])
    ]

    result = service.reconcile(
        "prod", OCM_CONNECTION, [cluster], VAULT_TARGET, dry_run=False
    )

    assert result.status == TaskStatus.SUCCESS
    assert len(result.applied_actions) == 1
    assert result.applied_actions[0].action_type == "update"
    mock_workspace_client.update_identity_provider.assert_called_once()
    call_args = mock_workspace_client.update_identity_provider.call_args
    assert call_args[0][0] == cluster.cluster_id
    assert call_args[0][1] == "idp-1"


def test_reconcile_delete_skips_unmanaged_idp(
    service: OcmOidcIdpService, mock_workspace_client: MagicMock
) -> None:
    cluster = _cluster(oidc_enabled=False, enforced=False)
    mock_workspace_client.get_identity_providers.return_value = [
        _current_oidc_idp(name="some-other-idp")
    ]

    result = service.reconcile(
        "prod", OCM_CONNECTION, [cluster], VAULT_TARGET, dry_run=False
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []
    mock_workspace_client.delete_identity_provider.assert_not_called()


def test_reconcile_delete_removes_managed_idp_when_disabled(
    service: OcmOidcIdpService, mock_workspace_client: MagicMock
) -> None:
    cluster = _cluster(oidc_enabled=False)
    mock_workspace_client.get_identity_providers.return_value = [
        _current_oidc_idp(idp_id="idp-1", name="redhat-sso")
    ]

    result = service.reconcile(
        "prod", OCM_CONNECTION, [cluster], VAULT_TARGET, dry_run=False
    )

    assert len(result.applied_actions) == 1
    assert result.applied_actions[0].action_type == "delete"
    mock_workspace_client.delete_identity_provider.assert_called_once_with(
        cluster.cluster_id, "idp-1"
    )


def test_reconcile_enforced_removes_foreign_idp(
    service: OcmOidcIdpService, mock_workspace_client: MagicMock
) -> None:
    cluster = _cluster(oidc_enabled=False, enforced=True)
    mock_workspace_client.get_identity_providers.return_value = [
        _current_oidc_idp(idp_id="idp-github", name="github")
    ]

    result = service.reconcile(
        "prod", OCM_CONNECTION, [cluster], VAULT_TARGET, dry_run=False
    )

    assert len(result.applied_actions) == 1
    mock_workspace_client.delete_identity_provider.assert_called_once_with(
        cluster.cluster_id, "idp-github"
    )


def test_reconcile_delete_missing_id_produces_error(
    service: OcmOidcIdpService, mock_workspace_client: MagicMock
) -> None:
    cluster = _cluster(oidc_enabled=False)
    idp_without_id = _current_oidc_idp(idp_id="idp-1", name="redhat-sso").model_copy(
        update={"id": None}
    )
    mock_workspace_client.get_identity_providers.return_value = [idp_without_id]

    result = service.reconcile(
        "prod", OCM_CONNECTION, [cluster], VAULT_TARGET, dry_run=False
    )

    assert result.status == TaskStatus.FAILED
    assert result.actions == []
    assert len(result.errors) == 1
    mock_workspace_client.delete_identity_provider.assert_not_called()


def test_reconcile_action_execution_failure_isolated(
    service: OcmOidcIdpService,
    mock_secret_manager: MagicMock,
    mock_workspace_client: MagicMock,
) -> None:
    cluster = _cluster()
    mock_secret_manager.read_all.return_value = _stored_secret(cluster)
    mock_workspace_client.create_identity_provider.side_effect = RuntimeError("boom")

    result = service.reconcile(
        "prod", OCM_CONNECTION, [cluster], VAULT_TARGET, dry_run=False
    )

    assert result.status == TaskStatus.FAILED
    assert len(result.actions) == 1
    assert result.applied_actions == []
    assert len(result.errors) == 1
    assert "boom" in result.errors[0]


def test_reconcile_current_state_fetch_error_isolated_per_cluster(
    service: OcmOidcIdpService, mock_workspace_client: MagicMock
) -> None:
    failing_cluster = _cluster(
        name="failing-cluster", cluster_id="cluster-fail", oidc_enabled=False
    )
    ok_cluster = _cluster(
        name="ok-cluster", cluster_id="cluster-ok", oidc_enabled=False
    )

    def _get_idps(cluster_id: str) -> list[OcmIdentityProviderOidc]:
        if cluster_id == "cluster-fail":
            raise RuntimeError("OCM unreachable")
        return [_current_oidc_idp(idp_id="idp-1", name="redhat-sso")]

    mock_workspace_client.get_identity_providers.side_effect = _get_idps

    result = service.reconcile(
        "prod",
        OCM_CONNECTION,
        [failing_cluster, ok_cluster],
        VAULT_TARGET,
        dry_run=False,
    )

    # The ok-cluster's managed idp is still correctly diffed and deleted (since
    # oidc_enabled=False means it's no longer desired); the failing cluster is
    # silently skipped for this reconcile, not surfaced as a fatal error.
    assert result.status == TaskStatus.SUCCESS
    assert len(result.applied_actions) == 1
    mock_workspace_client.delete_identity_provider.assert_called_once_with(
        "cluster-ok", "idp-1"
    )


def test_reconcile_desired_state_malformed_secret_isolated(
    service: OcmOidcIdpService, mock_secret_manager: MagicMock
) -> None:
    """A malformed/incomplete Vault secret must not crash the whole reconcile.

    Regression test for the legacy fragility this migration deliberately fixes: the
    old integration let a pydantic ValidationError from a malformed secret propagate
    and abort the entire OCM-environment run. This is NOT a reconcile error, though -
    it's the routine, extremely common state while sso_client hasn't reconciled this
    cluster yet (e.g. right after a cluster becomes RHIDP-enabled), so it must only be
    a warning, never fail the run or increment the error counter.
    """
    cluster = _cluster()
    mock_secret_manager.read_all.return_value = {"client_id": "only-one-field"}

    result = service.reconcile(
        "prod", OCM_CONNECTION, [cluster], VAULT_TARGET, dry_run=True
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []
    assert result.errors == []


def test_reconcile_desired_state_issuer_mismatch_skipped(
    service: OcmOidcIdpService, mock_secret_manager: MagicMock
) -> None:
    """Unlike a not-yet-created secret, an issuer mismatch can only happen if someone

    manually changed or copied the secret - a genuine misconfiguration, so it IS a
    reconcile error.
    """
    cluster = _cluster()
    mock_secret_manager.read_all.return_value = _stored_secret(
        cluster, issuer="https://different-issuer.example.com"
    )

    result = service.reconcile(
        "prod", OCM_CONNECTION, [cluster], VAULT_TARGET, dry_run=True
    )

    assert result.status == TaskStatus.FAILED
    assert result.actions == []
    assert len(result.errors) == 1
    assert "does not match configured cluster issuer" in result.errors[0]


def test_reconcile_unreadable_secret_does_not_delete_existing_idp(
    service: OcmOidcIdpService,
    mock_secret_manager: MagicMock,
    mock_workspace_client: MagicMock,
) -> None:
    """A cluster with a live, managed identity provider must not have it deleted

    just because its Vault secret became transiently unreadable this run. Before the
    fix, an unresolvable desired state looked identical to "not desired" to the diff,
    so the existing identity provider (name matches cluster.auth.name) would land in
    the delete bucket and be removed - a transient Vault hiccup silently destroying a
    working configuration. Regression test for that bug. Non-fatal (routine), so the
    run still succeeds overall - only the delete must not happen.
    """
    cluster = _cluster()
    mock_secret_manager.read_all.return_value = {"client_id": "only-one-field"}
    mock_workspace_client.get_identity_providers.return_value = [
        _current_oidc_idp(idp_id="idp-1", name="redhat-sso")
    ]

    result = service.reconcile(
        "prod", OCM_CONNECTION, [cluster], VAULT_TARGET, dry_run=False
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []
    assert result.applied_actions == []
    mock_workspace_client.delete_identity_provider.assert_not_called()


def test_reconcile_issuer_mismatch_does_not_delete_existing_idp(
    service: OcmOidcIdpService,
    mock_secret_manager: MagicMock,
    mock_workspace_client: MagicMock,
) -> None:
    """Same protection as the unreadable-secret case above, but for the fatal

    (issuer-mismatch) branch - a real misconfiguration must still be reported as an
    error, but must not cause the existing identity provider to be deleted either.
    """
    cluster = _cluster()
    mock_secret_manager.read_all.return_value = _stored_secret(
        cluster, issuer="https://different-issuer.example.com"
    )
    mock_workspace_client.get_identity_providers.return_value = [
        _current_oidc_idp(idp_id="idp-1", name="redhat-sso")
    ]

    result = service.reconcile(
        "prod", OCM_CONNECTION, [cluster], VAULT_TARGET, dry_run=False
    )

    assert result.status == TaskStatus.FAILED
    assert result.actions == []
    assert result.applied_actions == []
    assert len(result.errors) == 1
    mock_workspace_client.delete_identity_provider.assert_not_called()


def test_process_adds_skips_non_oidc_desired_idp(
    mock_workspace_client: MagicMock,
) -> None:
    """Desired state should never contain non-OIDC IDPs.

    But the executor must not blow up (or silently create something wrong) if it did.
    """
    cluster = _cluster()
    foreign = OcmIdentityProvider(type="GithubIdentityProvider", name="github")
    state = _IdpState(cluster=cluster, idp=foreign)

    actions, applied, errors = OcmOidcIdpService._process_adds(
        mock_workspace_client, [state], dry_run=False
    )

    assert actions == []
    assert applied == []
    assert errors == []
    mock_workspace_client.create_identity_provider.assert_not_called()


def test_reconcile_exposes_cluster_metrics(
    service: OcmOidcIdpService, mock_workspace_client: MagicMock
) -> None:
    cluster = _cluster(org_id="metrics-org", oidc_enabled=False)

    service.reconcile(
        "test-env-metrics", OCM_CONNECTION, [cluster], VAULT_TARGET, dry_run=True
    )

    assert (
        rhidp_managed_clusters.labels(
            "ocm-oidc-idp", "test-env-metrics", "metrics-org"
        )._value.get()
        == 1
    )


def test_reconcile_increments_error_counter_on_failure(
    service: OcmOidcIdpService,
    mock_secret_manager: MagicMock,
    mock_workspace_client: MagicMock,
) -> None:
    cluster = _cluster()
    mock_secret_manager.read_all.return_value = _stored_secret(cluster)
    mock_workspace_client.create_identity_provider.side_effect = RuntimeError("boom")

    before = rhidp_ocm_oidc_idp_reconcile_errors.labels(
        "ocm-oidc-idp", "error-env"
    )._value.get()

    service.reconcile(
        "error-env", OCM_CONNECTION, [cluster], VAULT_TARGET, dry_run=False
    )

    after = rhidp_ocm_oidc_idp_reconcile_errors.labels(
        "ocm-oidc-idp", "error-env"
    )._value.get()
    assert after == before + 1
