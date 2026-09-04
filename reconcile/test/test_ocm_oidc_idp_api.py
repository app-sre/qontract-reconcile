"""Tests for the ocm-oidc-idp-api client-side integration."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from qontract_api_client.schemas import (
    OcmClusterInfo,
    OcmClustersResponse,
    OcmOidcIdpActionCreate,
    OcmOidcIdpActionDelete,
    OcmOidcIdpActionUpdate,
    OcmOidcIdpTaskResponse,
    OcmOidcIdpTaskResult,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.rhidp_api.ocm_oidc_idp.integration import (
    OCMOidcIdpApiIntegration,
    OCMOidcIdpApiIntegrationParams,
    build_clusters,
)

SECRET_MANAGER_URL = "https://vault.example.com"

OcmOidcIdpAction = (
    OcmOidcIdpActionCreate | OcmOidcIdpActionUpdate | OcmOidcIdpActionDelete
)


class _TestableIntegration(OCMOidcIdpApiIntegration):
    @property
    def secret_manager_url(self) -> str:
        return SECRET_MANAGER_URL


def make_integration(ocm_environment: str | None = None) -> _TestableIntegration:
    return _TestableIntegration(
        OCMOidcIdpApiIntegrationParams(
            vault_input_path="rhidp/sso-client",
            ocm_environment=ocm_environment,
            default_auth_name="redhat-sso",
            default_auth_issuer_url="https://default-issuer.example.com",
        )
    )


def make_ocm_environment(name: str = "prod") -> OCMEnvironment:
    return OCMEnvironment(
        name=name,
        description=None,
        labels=None,
        url="https://api.openshift.com",
        accessTokenClientId="client-id",
        accessTokenUrl="https://sso.redhat.com/token",
        accessTokenClientSecret=VaultSecret(
            path="app-sre/creds/ocm", field="client_secret", version=None, format=None
        ),
    )


def make_ocm_cluster(
    name: str = "my-cluster",
    *,
    console_url: str | None = "https://console.example.com",
    external_auth_enabled: bool = False,
    labels: dict[str, Any] | None = None,
) -> OcmClusterInfo:
    return OcmClusterInfo(
        id="cluster-1",
        name=name,
        organization_id="org-1",
        console_url=console_url,
        external_auth_enabled=external_auth_enabled,
        labels=labels or {},
    )


def make_task_response(task_id: str = "task-123") -> OcmOidcIdpTaskResponse:
    return OcmOidcIdpTaskResponse(
        id=task_id, status=TaskStatus.PENDING, status_url=f"/tasks/{task_id}"
    )


def make_task_result(
    status: TaskStatus = TaskStatus.SUCCESS,
    actions: list[OcmOidcIdpAction] | None = None,
    errors: list[str] | None = None,
) -> OcmOidcIdpTaskResult:
    return OcmOidcIdpTaskResult(
        status=status, actions=actions or [], errors=errors or []
    )


# ---------------------------------------------------------------------------
# build_clusters
# ---------------------------------------------------------------------------


def test_build_clusters_no_labels_uses_defaults() -> None:
    result = build_clusters(
        [make_ocm_cluster()], "redhat-sso", "https://default-issuer.example.com"
    )

    assert len(result) == 1
    assert result[0].auth.name == "redhat-sso"
    assert result[0].auth.issuer == "https://default-issuer.example.com"
    assert result[0].auth.oidc_enabled is False  # no status label -> disabled
    assert result[0].auth.enforced is False


def test_build_clusters_uses_label_overrides() -> None:
    result = build_clusters(
        [
            make_ocm_cluster(
                labels={
                    "sre-capabilities.rhidp.name": "custom-auth",
                    "sre-capabilities.rhidp.issuer": "https://custom-issuer",
                    "sre-capabilities.rhidp.status": "enabled",
                    "sre-capabilities.rhidp.group-filter-regex": "^team-.*$",
                }
            )
        ],
        "redhat-sso",
        "https://default-issuer.example.com",
    )

    assert result[0].auth.name == "custom-auth"
    assert result[0].auth.issuer == "https://custom-issuer"
    assert result[0].auth.oidc_enabled is True
    assert result[0].auth.enforced is False
    assert result[0].auth.group_filter_regex == "^team-.*$"


@pytest.mark.parametrize(
    ("status_label", "expected_oidc_enabled", "expected_enforced"),
    [
        pytest.param(None, False, False, id="no-status-label"),
        pytest.param("enabled", True, False, id="enabled"),
        pytest.param("enforced", True, True, id="enforced"),
        pytest.param("sso-client-only", False, False, id="sso-client-only"),
        pytest.param("disabled", False, False, id="disabled"),
    ],
)
def test_build_clusters_status_label_maps_to_oidc_flags(
    status_label: str | None,
    expected_oidc_enabled: bool,
    expected_enforced: bool,
) -> None:
    """Disabled/no-label clusters must still be included (not excluded outright),

    so the server can still diff and clean up any leftover identity provider from
    before the cluster became disabled.
    """
    labels = {"sre-capabilities.rhidp.status": status_label} if status_label else None

    result = build_clusters(
        [make_ocm_cluster(labels=labels)],
        "redhat-sso",
        "https://default-issuer.example.com",
    )

    assert len(result) == 1
    assert result[0].auth.oidc_enabled is expected_oidc_enabled
    assert result[0].auth.enforced is expected_enforced


def test_build_clusters_excludes_ignored_clusters() -> None:
    result = build_clusters(
        [
            make_ocm_cluster(
                name="ignored-cluster",
                labels={"sre-capabilities.rhidp.status": "ignored"},
            ),
            make_ocm_cluster(name="not-ignored-cluster"),
        ],
        "redhat-sso",
        "https://default-issuer.example.com",
    )

    assert [cluster.name for cluster in result] == ["not-ignored-cluster"]


def test_build_clusters_deprecated_bare_rhidp_label_takes_precedence() -> None:
    result = build_clusters(
        [
            make_ocm_cluster(
                labels={
                    "sre-capabilities.rhidp": "enabled",
                    "sre-capabilities.rhidp.status": "disabled",
                }
            )
        ],
        "redhat-sso",
        "https://default-issuer.example.com",
    )

    assert result[0].auth.oidc_enabled is True


@pytest.mark.parametrize(
    ("console_url", "external_auth_enabled"),
    [
        pytest.param(None, False, id="no-console-url"),
        pytest.param("https://console.example.com", True, id="external-auth-enabled"),
    ],
)
def test_build_clusters_excludes_not_ready_clusters(
    console_url: str | None, external_auth_enabled: bool
) -> None:
    result = build_clusters(
        [
            make_ocm_cluster(
                console_url=console_url, external_auth_enabled=external_auth_enabled
            )
        ],
        "redhat-sso",
        "https://default-issuer.example.com",
    )

    assert result == []


# ---------------------------------------------------------------------------
# async_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_waits_for_task_and_logs_actions() -> None:
    integration = make_integration()
    task_response = make_task_response()
    action = OcmOidcIdpActionCreate(cluster_name="my-cluster", auth_name="redhat-sso")
    task_result = make_task_result(actions=[action])

    with (
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.get_ocm_environments",
            return_value=[make_ocm_environment()],
        ),
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.get_ocm_orgs_from_env",
            return_value=[],
        ),
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.ocm_clusters",
            new=AsyncMock(
                return_value=OcmClustersResponse(clusters=[make_ocm_cluster()])
            ),
        ),
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.ocm_oidc_idp",
            new=AsyncMock(return_value=task_response),
        ) as mock_ocm_oidc_idp,
        patch.object(
            integration, "poll_task_status", new=AsyncMock(return_value=task_result)
        ),
    ):
        await integration.async_run(dry_run=True)

        request = mock_ocm_oidc_idp.call_args.args[0]
        assert request.ocm_environment == "prod"
        assert request.dry_run is True
        assert request.ocm_connection.ocm_url == "https://api.openshift.com"
        assert request.ocm_connection.secret_manager_url == SECRET_MANAGER_URL
        assert request.vault_target.path == "rhidp/sso-client/prod"
        assert request.vault_target.secret_manager_url == SECRET_MANAGER_URL


@pytest.mark.asyncio
async def test_non_dry_run_does_not_wait_for_task() -> None:
    integration = make_integration()
    task_response = make_task_response()

    with (
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.get_ocm_environments",
            return_value=[make_ocm_environment()],
        ),
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.get_ocm_orgs_from_env",
            return_value=[],
        ),
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.ocm_clusters",
            new=AsyncMock(return_value=OcmClustersResponse(clusters=[])),
        ),
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.ocm_oidc_idp",
            new=AsyncMock(return_value=task_response),
        ),
        patch.object(integration, "poll_task_status") as mock_status,
    ):
        await integration.async_run(dry_run=False)
        mock_status.assert_not_called()


@pytest.mark.asyncio
async def test_sends_request_even_with_zero_clusters() -> None:
    """Even zero discovered clusters must still POST - the backend needs an empty
    clusters list to detect and delete stale identity providers.
    """
    integration = make_integration()
    task_response = make_task_response()

    with (
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.get_ocm_environments",
            return_value=[make_ocm_environment()],
        ),
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.get_ocm_orgs_from_env",
            return_value=[],
        ),
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.ocm_clusters",
            new=AsyncMock(return_value=OcmClustersResponse(clusters=[])),
        ),
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.ocm_oidc_idp",
            new=AsyncMock(return_value=task_response),
        ) as mock_ocm_oidc_idp,
        patch.object(integration, "poll_task_status"),
    ):
        await integration.async_run(dry_run=False)
        mock_ocm_oidc_idp.assert_called_once()
        assert mock_ocm_oidc_idp.call_args.args[0].clusters == []


@pytest.mark.asyncio
async def test_dry_run_raises_on_errors() -> None:
    integration = make_integration()
    task_response = make_task_response()
    task_result = make_task_result(errors=["something went wrong"])

    with (
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.get_ocm_environments",
            return_value=[make_ocm_environment()],
        ),
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.get_ocm_orgs_from_env",
            return_value=[],
        ),
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.ocm_clusters",
            new=AsyncMock(return_value=OcmClustersResponse(clusters=[])),
        ),
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.ocm_oidc_idp",
            new=AsyncMock(return_value=task_response),
        ),
        patch.object(
            integration, "poll_task_status", new=AsyncMock(return_value=task_result)
        ),
        pytest.raises(IntegrationError),
    ):
        await integration.async_run(dry_run=True)


@pytest.mark.asyncio
async def test_dry_run_raises_on_timeout() -> None:
    integration = make_integration()
    task_response = make_task_response()
    task_result = make_task_result(status=TaskStatus.PENDING)

    with (
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.get_ocm_environments",
            return_value=[make_ocm_environment()],
        ),
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.get_ocm_orgs_from_env",
            return_value=[],
        ),
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.ocm_clusters",
            new=AsyncMock(return_value=OcmClustersResponse(clusters=[])),
        ),
        patch(
            "reconcile.rhidp_api.ocm_oidc_idp.integration.ocm_oidc_idp",
            new=AsyncMock(return_value=task_response),
        ),
        patch.object(
            integration, "poll_task_status", new=AsyncMock(return_value=task_result)
        ),
        pytest.raises(IntegrationError),
    ):
        await integration.async_run(dry_run=True)
