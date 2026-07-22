"""Tests for the rhidp-sso-client-api client-side integration."""

from unittest.mock import AsyncMock, patch

import pytest
from qontract_api_client.schemas import (
    KeycloakInstanceSecret,
    OcmClusterInfo,
    OcmClustersResponse,
    Secret,
    SsoClientActionCreate,
    SsoClientTaskResponse,
    SsoClientTaskResult,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.rhidp_api.sso_client.integration import (
    SSOClientApiIntegration,
    SSOClientApiIntegrationParams,
    build_clusters,
)

SECRET_MANAGER_URL = "https://vault.example.com"
KEYCLOAK_VAULT_URL = "https://keycloak-vault.example.com"
KEYCLOAK_ISSUER_URL = "https://issuer.example.com"


class _TestableIntegration(SSOClientApiIntegration):
    @property
    def secret_manager_url(self) -> str:
        return SECRET_MANAGER_URL


def make_integration(ocm_environment: str | None = None) -> _TestableIntegration:
    return _TestableIntegration(
        SSOClientApiIntegrationParams(
            keycloak_instances=[
                KeycloakInstanceSecret(
                    url=KEYCLOAK_ISSUER_URL,
                    secret=Secret(
                        secret_manager_url=KEYCLOAK_VAULT_URL,
                        path="keycloak/instance1",
                    ),
                )
            ],
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
    labels: dict | None = None,
) -> OcmClusterInfo:
    return OcmClusterInfo(
        id="cluster-1",
        name=name,
        organization_id="org-1",
        console_url=console_url,
        external_auth_enabled=external_auth_enabled,
        labels=labels or {},
    )


# ---------------------------------------------------------------------------
# build_clusters
# ---------------------------------------------------------------------------


class TestBuildClusters:
    def test_uses_default_auth_when_no_labels(self) -> None:
        result = build_clusters(
            [make_ocm_cluster()], "redhat-sso", "https://default-issuer.example.com"
        )

        assert len(result) == 1
        assert result[0].auth.name == "redhat-sso"
        assert result[0].auth.issuer == "https://default-issuer.example.com"
        assert result[0].rhidp_enabled is False  # no status label -> disabled

    def test_uses_label_overrides(self) -> None:
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
        assert result[0].rhidp_enabled is True
        assert result[0].auth.group_filter_regex == "^team-.*$"

    def test_deprecated_bare_rhidp_label_takes_precedence(self) -> None:
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

        assert result[0].rhidp_enabled is True

    def test_excludes_cluster_without_console_url(self) -> None:
        result = build_clusters(
            [make_ocm_cluster(console_url=None)],
            "redhat-sso",
            "https://default-issuer.example.com",
        )

        assert result == []

    def test_excludes_cluster_with_external_auth_enabled(self) -> None:
        result = build_clusters(
            [make_ocm_cluster(external_auth_enabled=True)],
            "redhat-sso",
            "https://default-issuer.example.com",
        )

        assert result == []

    def test_disabled_clusters_still_included(self) -> None:
        """Disabled clusters must still be sent (for the rhidp_managed_clusters metric)."""
        result = build_clusters(
            [make_ocm_cluster(labels={"sre-capabilities.rhidp.status": "disabled"})],
            "redhat-sso",
            "https://default-issuer.example.com",
        )

        assert len(result) == 1
        assert result[0].rhidp_enabled is False


# ---------------------------------------------------------------------------
# async_run
# ---------------------------------------------------------------------------


class TestAsyncRun:
    def _make_task_response(self, task_id: str = "task-123") -> SsoClientTaskResponse:
        return SsoClientTaskResponse(
            id=task_id, status=TaskStatus.PENDING, status_url=f"/tasks/{task_id}"
        )

    def _make_task_result(
        self,
        status: TaskStatus = TaskStatus.SUCCESS,
        actions: list | None = None,
        errors: list | None = None,
    ) -> SsoClientTaskResult:
        return SsoClientTaskResult(
            status=status, actions=actions or [], errors=errors or []
        )

    @pytest.mark.asyncio
    async def test_dry_run_waits_for_task_and_logs_actions(self) -> None:
        integration = make_integration()
        task_response = self._make_task_response()
        action = SsoClientActionCreate(
            sso_client_id="c1", cluster_name="my-cluster", auth_name="redhat-sso"
        )
        task_result = self._make_task_result(actions=[action])

        with (
            patch(
                "reconcile.rhidp_api.sso_client.integration.get_ocm_environments",
                return_value=[make_ocm_environment()],
            ),
            patch(
                "reconcile.rhidp_api.sso_client.integration.get_ocm_orgs_from_env",
                return_value=[],
            ),
            patch(
                "reconcile.rhidp_api.sso_client.integration.ocm_clusters",
                new=AsyncMock(
                    return_value=OcmClustersResponse(clusters=[make_ocm_cluster()])
                ),
            ),
            patch(
                "reconcile.rhidp_api.sso_client.integration.sso_client",
                new=AsyncMock(return_value=task_response),
            ) as mock_sso_client,
            patch.object(
                integration, "poll_task_status", new=AsyncMock(return_value=task_result)
            ),
        ):
            await integration.async_run(dry_run=True)

            request = mock_sso_client.call_args.args[0]
            assert request.ocm_environment == "prod"
            assert request.dry_run is True
            assert request.keycloak_secrets[0].url == KEYCLOAK_ISSUER_URL
            assert (
                request.keycloak_secrets[0].secret.secret_manager_url
                == KEYCLOAK_VAULT_URL
            )
            assert request.vault_target.path == "rhidp/sso-client/prod"
            assert request.vault_target.secret_manager_url == SECRET_MANAGER_URL

    @pytest.mark.asyncio
    async def test_non_dry_run_does_not_wait_for_task(self) -> None:
        integration = make_integration()
        task_response = self._make_task_response()

        with (
            patch(
                "reconcile.rhidp_api.sso_client.integration.get_ocm_environments",
                return_value=[make_ocm_environment()],
            ),
            patch(
                "reconcile.rhidp_api.sso_client.integration.get_ocm_orgs_from_env",
                return_value=[],
            ),
            patch(
                "reconcile.rhidp_api.sso_client.integration.ocm_clusters",
                new=AsyncMock(return_value=OcmClustersResponse(clusters=[])),
            ),
            patch(
                "reconcile.rhidp_api.sso_client.integration.sso_client",
                new=AsyncMock(return_value=task_response),
            ),
            patch.object(integration, "poll_task_status") as mock_status,
        ):
            await integration.async_run(dry_run=False)
            mock_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_request_even_with_zero_clusters(self) -> None:
        """Even zero discovered clusters must still POST - the backend needs an empty
        clusters list to detect and delete stale SSO clients."""
        integration = make_integration()
        task_response = self._make_task_response()

        with (
            patch(
                "reconcile.rhidp_api.sso_client.integration.get_ocm_environments",
                return_value=[make_ocm_environment()],
            ),
            patch(
                "reconcile.rhidp_api.sso_client.integration.get_ocm_orgs_from_env",
                return_value=[],
            ),
            patch(
                "reconcile.rhidp_api.sso_client.integration.ocm_clusters",
                new=AsyncMock(return_value=OcmClustersResponse(clusters=[])),
            ),
            patch(
                "reconcile.rhidp_api.sso_client.integration.sso_client",
                new=AsyncMock(return_value=task_response),
            ) as mock_sso_client,
            patch.object(integration, "poll_task_status"),
        ):
            await integration.async_run(dry_run=False)
            mock_sso_client.assert_called_once()
            assert mock_sso_client.call_args.args[0].clusters == []

    @pytest.mark.asyncio
    async def test_dry_run_raises_on_errors(self) -> None:
        integration = make_integration()
        task_response = self._make_task_response()
        task_result = self._make_task_result(errors=["something went wrong"])

        with (
            patch(
                "reconcile.rhidp_api.sso_client.integration.get_ocm_environments",
                return_value=[make_ocm_environment()],
            ),
            patch(
                "reconcile.rhidp_api.sso_client.integration.get_ocm_orgs_from_env",
                return_value=[],
            ),
            patch(
                "reconcile.rhidp_api.sso_client.integration.ocm_clusters",
                new=AsyncMock(return_value=OcmClustersResponse(clusters=[])),
            ),
            patch(
                "reconcile.rhidp_api.sso_client.integration.sso_client",
                new=AsyncMock(return_value=task_response),
            ),
            patch.object(
                integration, "poll_task_status", new=AsyncMock(return_value=task_result)
            ),
            pytest.raises(IntegrationError),
        ):
            await integration.async_run(dry_run=True)

    @pytest.mark.asyncio
    async def test_dry_run_raises_on_timeout(self) -> None:
        integration = make_integration()
        task_response = self._make_task_response()
        task_result = self._make_task_result(status=TaskStatus.PENDING)

        with (
            patch(
                "reconcile.rhidp_api.sso_client.integration.get_ocm_environments",
                return_value=[make_ocm_environment()],
            ),
            patch(
                "reconcile.rhidp_api.sso_client.integration.get_ocm_orgs_from_env",
                return_value=[],
            ),
            patch(
                "reconcile.rhidp_api.sso_client.integration.ocm_clusters",
                new=AsyncMock(return_value=OcmClustersResponse(clusters=[])),
            ),
            patch(
                "reconcile.rhidp_api.sso_client.integration.sso_client",
                new=AsyncMock(return_value=task_response),
            ),
            patch.object(
                integration, "poll_task_status", new=AsyncMock(return_value=task_result)
            ),
            pytest.raises(IntegrationError),
        ):
            await integration.async_run(dry_run=True)
