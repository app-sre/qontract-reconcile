"""Tests for the ocm-groups-api client-side integration."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from qontract_api_client.schemas import (
    OcmGroupsActionAddUser,
    OcmGroupsActionDeleteUser,
    OcmGroupsTaskResponse,
    OcmGroupsTaskResult,
    OcmGroupUser,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.ocm_groups_api.clusters import (
    ClusterAuthV1,
    ClusterSpecV1,
    ClusterV1,
    OpenShiftClusterManagerV1,
)
from reconcile.ocm_groups_api import (
    OcmGroupsIntegration,
    OcmGroupsIntegrationParams,
)

SECRET_MANAGER_URL = "https://vault.example.com"

# Module path for patching
_MOD = "reconcile.ocm_groups_api"

OcmGroupsAction = OcmGroupsActionAddUser | OcmGroupsActionDeleteUser


class _TestableIntegration(OcmGroupsIntegration):
    @property
    def secret_manager_url(self) -> str:
        return SECRET_MANAGER_URL


def make_integration() -> _TestableIntegration:
    return _TestableIntegration(OcmGroupsIntegrationParams())


def make_cluster(
    name: str = "my-cluster",
    *,
    spec_id: str = "cluster-1",
    managed_groups: list[str] | None = None,
    with_ocm: bool = True,
    ocm_env_name: str = "ocm-production",
    access_token_client_id: str = "client-id",
    access_token_url: str = "https://sso.redhat.com/token",
    secret_path: str = "app-sre/creds/ocm",
    secret_field: str = "client_secret",
    ocm_url: str = "https://api.openshift.com",
) -> ClusterV1:
    """Build a typed ClusterV1 matching the GQL schema."""
    ocm = None
    if with_ocm:
        ocm = OpenShiftClusterManagerV1(
            name=ocm_env_name,
            environment=OCMEnvironment(
                name=ocm_env_name,
                description=f"{ocm_env_name} env",
                labels=None,
                url=ocm_url,
                accessTokenClientId=access_token_client_id,
                accessTokenUrl=access_token_url,
                accessTokenClientSecret=VaultSecret(
                    path=secret_path,
                    field=secret_field,
                    version=None,
                    format=None,
                ),
            ),
            accessTokenClientId=access_token_client_id,
            accessTokenUrl=access_token_url,
            accessTokenClientSecret=VaultSecret(
                path=secret_path,
                field=secret_field,
                version=None,
                format=None,
            ),
        )
    return ClusterV1(
        name=name,
        managedGroups=managed_groups
        if managed_groups is not None
        else ["dedicated-admins"],
        spec=ClusterSpecV1(id=spec_id),
        auth=[ClusterAuthV1(service="github-org")],
        ocm=ocm,
        disable=None,
    )


def make_task_response(task_id: str = "task-123") -> OcmGroupsTaskResponse:
    return OcmGroupsTaskResponse(
        id=task_id, status=TaskStatus.PENDING, status_url=f"/tasks/{task_id}"
    )


def make_task_result(
    status: TaskStatus = TaskStatus.SUCCESS,
    actions: list[OcmGroupsAction] | None = None,
    errors: list[str] | None = None,
) -> OcmGroupsTaskResult:
    return OcmGroupsTaskResult(
        status=status, actions=actions or [], errors=errors or []
    )


# ---------------------------------------------------------------------------
# async_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_polls_task_and_logs_actions() -> None:
    integration = make_integration()
    task_response = make_task_response()
    action = OcmGroupsActionAddUser(
        cluster="my-cluster", group="dedicated-admins", user="alice"
    )
    task_result = make_task_result(actions=[action])

    with (
        patch(f"{_MOD}._get_clusters", return_value=[make_cluster()]),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(
            f"{_MOD}._fetch_desired_state",
            return_value=[
                OcmGroupUser(
                    cluster="my-cluster",
                    group="dedicated-admins",
                    user="alice",
                )
            ],
        ),
        patch(
            f"{_MOD}.reconcile_ocm_groups",
            new=AsyncMock(return_value=task_response),
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=task_result),
        ),
    ):
        await integration.async_run(dry_run=True)

        request = mock_reconcile.call_args.args[0]
        assert request.dry_run is True
        assert request.ocm_environment == "ocm-production"
        assert request.ocm_connection.ocm_url == "https://api.openshift.com"
        assert request.ocm_connection.secret_manager_url == SECRET_MANAGER_URL
        assert len(request.clusters) == 1
        assert request.clusters[0].name == "my-cluster"
        assert request.clusters[0].cluster_id == "cluster-1"
        assert request.clusters[0].managed_groups == ["dedicated-admins"]
        assert len(request.desired_state) == 1
        assert request.desired_state[0].user == "alice"


@pytest.mark.asyncio
async def test_non_dry_run_also_polls_task() -> None:
    """Unlike ocm-oidc-idp, ocm-groups always polls — server-side errors must
    always be surfaced regardless of dry_run mode.
    """
    integration = make_integration()
    task_response = make_task_response()
    task_result = make_task_result()

    with (
        patch(f"{_MOD}._get_clusters", return_value=[make_cluster()]),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(f"{_MOD}._fetch_desired_state", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ocm_groups",
            new=AsyncMock(return_value=task_response),
        ),
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=task_result),
        ) as mock_status,
    ):
        await integration.async_run(dry_run=False)
        mock_status.assert_called_once()


@pytest.mark.asyncio
async def test_sends_request_with_empty_desired_state() -> None:
    """Even with zero desired memberships the server needs the cluster list to
    clean up stale users.
    """
    integration = make_integration()
    task_response = make_task_response()
    task_result = make_task_result()

    with (
        patch(f"{_MOD}._get_clusters", return_value=[make_cluster()]),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(f"{_MOD}._fetch_desired_state", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ocm_groups",
            new=AsyncMock(return_value=task_response),
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=task_result),
        ),
    ):
        await integration.async_run(dry_run=True)
        mock_reconcile.assert_called_once()
        assert mock_reconcile.call_args.args[0].desired_state == []


@pytest.mark.asyncio
async def test_raises_on_errors() -> None:
    integration = make_integration()
    task_response = make_task_response()
    task_result = make_task_result(errors=["something went wrong"])

    with (
        patch(f"{_MOD}._get_clusters", return_value=[make_cluster()]),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(f"{_MOD}._fetch_desired_state", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ocm_groups",
            new=AsyncMock(return_value=task_response),
        ),
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=task_result),
        ),
        pytest.raises(IntegrationError),
    ):
        await integration.async_run(dry_run=True)


@pytest.mark.asyncio
async def test_raises_on_timeout() -> None:
    integration = make_integration()
    task_response = make_task_response()
    task_result = make_task_result(status=TaskStatus.PENDING)

    with (
        patch(f"{_MOD}._get_clusters", return_value=[make_cluster()]),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(f"{_MOD}._fetch_desired_state", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ocm_groups",
            new=AsyncMock(return_value=task_response),
        ),
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=task_result),
        ),
        pytest.raises(IntegrationError),
    ):
        await integration.async_run(dry_run=True)


@pytest.mark.asyncio
async def test_no_clusters_returns_early() -> None:
    integration = make_integration()

    with (
        patch(f"{_MOD}._get_clusters", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ocm_groups",
            new=AsyncMock(),
        ) as mock_reconcile,
    ):
        await integration.async_run(dry_run=True)
        mock_reconcile.assert_not_called()


@pytest.mark.asyncio
async def test_skips_non_ocm_clusters() -> None:
    """Clusters without an OCM configuration are filtered out."""
    integration = make_integration()

    with (
        patch(
            f"{_MOD}._get_clusters",
            return_value=[make_cluster(with_ocm=False)],
        ),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(
            f"{_MOD}.reconcile_ocm_groups",
            new=AsyncMock(),
        ) as mock_reconcile,
    ):
        await integration.async_run(dry_run=True)
        mock_reconcile.assert_not_called()


@pytest.mark.asyncio
async def test_skips_clusters_without_valid_managed_groups() -> None:
    """Clusters whose managedGroups is empty or contains only non-OCM groups are
    skipped — only dedicated-admins/cluster-admins are valid OCM groups.
    """
    integration = make_integration()

    with (
        patch(
            f"{_MOD}._get_clusters",
            return_value=[make_cluster(managed_groups=["invalid-group"])],
        ),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(f"{_MOD}._fetch_desired_state", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ocm_groups",
            new=AsyncMock(),
        ) as mock_reconcile,
    ):
        await integration.async_run(dry_run=True)
        mock_reconcile.assert_not_called()


@pytest.mark.asyncio
async def test_filters_non_ocm_groups_from_desired_state() -> None:
    """Groups not in VALID_OCM_GROUPS (dedicated-admins, cluster-admins) are
    filtered from the desired state before sending to the server.
    """
    integration = make_integration()
    task_response = make_task_response()
    task_result = make_task_result()

    with (
        patch(f"{_MOD}._get_clusters", return_value=[make_cluster()]),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(
            f"{_MOD}._fetch_desired_state",
            return_value=[
                OcmGroupUser(
                    cluster="my-cluster",
                    group="dedicated-admins",
                    user="alice",
                ),
                OcmGroupUser(
                    cluster="my-cluster",
                    group="osd-sre-admins",
                    user="bob",
                ),
            ],
        ),
        patch(
            f"{_MOD}.reconcile_ocm_groups",
            new=AsyncMock(return_value=task_response),
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=task_result),
        ),
    ):
        await integration.async_run(dry_run=True)
        desired = mock_reconcile.call_args.args[0].desired_state
        assert len(desired) == 1
        assert desired[0].group == "dedicated-admins"


@pytest.mark.asyncio
async def test_ocm_connection_uses_first_cluster_config() -> None:
    """OCM connection is built from the first cluster's OCM configuration."""
    integration = make_integration()
    task_response = make_task_response()
    task_result = make_task_result()

    with (
        patch(
            f"{_MOD}._get_clusters",
            return_value=[
                make_cluster(name="first"),
                make_cluster(name="second"),
            ],
        ),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(f"{_MOD}._fetch_desired_state", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ocm_groups",
            new=AsyncMock(return_value=task_response),
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=task_result),
        ),
    ):
        await integration.async_run(dry_run=True)
        conn = mock_reconcile.call_args.args[0].ocm_connection
        assert conn.path == "app-sre/creds/ocm"
        assert conn.access_token_client_id == "client-id"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"secret_path": ""},
        {"access_token_client_id": ""},
        {"secret_path": "", "access_token_client_id": ""},
        {"ocm_env_name": ""},
    ],
    ids=[
        "missing-secret-path",
        "missing-client-id",
        "missing-both",
        "missing-environment-name",
    ],
)
async def test_raises_on_missing_ocm_credentials(
    overrides: dict[str, Any],
) -> None:
    """Missing accessTokenClientSecret.path or accessTokenClientId raises."""
    integration = make_integration()
    cluster = make_cluster(**overrides)

    with (
        patch(f"{_MOD}._get_clusters", return_value=[cluster]),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(f"{_MOD}._fetch_desired_state", return_value=[]),
        pytest.raises(IntegrationError, match="missing from cluster OCM configuration"),
    ):
        await integration.async_run(dry_run=True)


@pytest.mark.asyncio
async def test_per_env_reconciliation_sends_separate_requests() -> None:
    """Clusters in different OCM environments get separate reconcile requests."""
    integration = make_integration()
    task_response = make_task_response()
    task_result = make_task_result()

    prod_cluster = make_cluster(name="prod-cluster", ocm_env_name="ocm-prod")
    stage_cluster = make_cluster(name="stage-cluster", ocm_env_name="ocm-stage")

    with (
        patch(
            f"{_MOD}._get_clusters",
            return_value=[prod_cluster, stage_cluster],
        ),
        patch(f"{_MOD}.integration_is_enabled", return_value=True),
        patch(f"{_MOD}._fetch_desired_state", return_value=[]),
        patch(
            f"{_MOD}.reconcile_ocm_groups",
            new=AsyncMock(return_value=task_response),
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new=AsyncMock(return_value=task_result),
        ),
    ):
        await integration.async_run(dry_run=True)
        # Should be called once per environment
        assert mock_reconcile.call_count == 2
        envs_called = {
            call.args[0].ocm_environment for call in mock_reconcile.call_args_list
        }
        assert envs_called == {"ocm-prod", "ocm-stage"}
