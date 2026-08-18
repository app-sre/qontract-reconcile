"""Tests for the quay-repos-api client-side integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qontract_api_client.schemas import (
    QuayOrgKey,
    QuayReposTaskResponse,
    QuayReposTaskResult,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.quay_repos_api.apps_quay_repos import (
    AppQuayReposItemsV1,
    AppQuayReposV1,
    AppV1,
    QuayInstanceV1 as AppQuayInstanceV1,
    QuayOrgV1 as AppQuayOrgV1,
)
from reconcile.gql_definitions.quay_repos_api.quay_orgs import (
    QuayInstanceV1,
    QuayOrgV1,
    QuayOrgV1_QuayOrgV1,
    QuayOrgV1_QuayOrgV1_QuayInstanceV1,
    VaultSecretV1,
)
from reconcile.quay_repos_api import QuayReposIntegration, QuayReposIntegrationParams

SECRET_MANAGER_URL = "https://vault.example.com"


class _TestableIntegration(QuayReposIntegration):
    @property
    def secret_manager_url(self) -> str:
        return SECRET_MANAGER_URL


def _make_integration() -> _TestableIntegration:
    return _TestableIntegration(QuayReposIntegrationParams())


def _make_org(
    name: str = "myorg",
    instance_name: str = "quay.io",
    instance_url: str = "https://quay.io",
    managed_repos: bool = True,
    token_path: str = "secret/quay/myorg",
) -> QuayOrgV1:
    return QuayOrgV1(
        name=name,
        managedRepos=managed_repos,
        instance=QuayInstanceV1(name=instance_name, url=instance_url),
        automationToken=VaultSecretV1(path=token_path, field="token", version=None),
        mirror=None,
    )


def _make_org_no_token(
    name: str = "myorg",
    instance_name: str = "quay.io",
    instance_url: str = "https://quay.io",
) -> QuayOrgV1:
    return QuayOrgV1(
        name=name,
        managedRepos=True,
        instance=QuayInstanceV1(name=instance_name, url=instance_url),
        automationToken=None,
        mirror=None,
    )


def _make_org_with_mirror(
    name: str = "myorg",
    mirror_name: str = "upstream-org",
    mirror_instance: str = "quay.io",
    token_path: str = "secret/quay/myorg",
) -> QuayOrgV1:
    return QuayOrgV1(
        name=name,
        managedRepos=False,
        instance=QuayInstanceV1(name="quay.io", url="https://quay.io"),
        automationToken=VaultSecretV1(path=token_path, field="token", version=None),
        mirror=QuayOrgV1_QuayOrgV1(
            name=mirror_name,
            instance=QuayOrgV1_QuayOrgV1_QuayInstanceV1(name=mirror_instance),
        ),
    )


def _make_app(org_name: str, instance_name: str, repo_names: list[str]) -> AppV1:
    return AppV1(
        quayRepos=[
            AppQuayReposV1(
                org=AppQuayOrgV1(
                    name=org_name,
                    instance=AppQuayInstanceV1(name=instance_name),
                ),
                items=[
                    AppQuayReposItemsV1(name=r, public=True, description="desc")
                    for r in repo_names
                ],
            )
        ]
    )


# ---------------------------------------------------------------------------
# compile_desired_state — duplicate repo name detection
# ---------------------------------------------------------------------------


def test_compile_desired_state_duplicate_repo_raises() -> None:
    integration = _make_integration()
    org = _make_org()
    app1 = _make_app("myorg", "quay.io", ["shared-repo"])
    app2 = _make_app("myorg", "quay.io", ["shared-repo"])

    with pytest.raises(IntegrationError, match="duplicate repo name"):
        integration.compile_desired_state(orgs=[org], apps=[app1, app2])


def test_compile_desired_state_duplicate_includes_org_context() -> None:
    integration = _make_integration()
    org = _make_org(name="myorg", instance_name="quay.io")
    app1 = _make_app("myorg", "quay.io", ["conflict"])
    app2 = _make_app("myorg", "quay.io", ["conflict"])

    with pytest.raises(IntegrationError, match=r"quay\.io/myorg"):
        integration.compile_desired_state(orgs=[org], apps=[app1, app2])


def test_compile_desired_state_no_duplicate_succeeds() -> None:
    integration = _make_integration()
    org = _make_org()
    app1 = _make_app("myorg", "quay.io", ["repo-a"])
    app2 = _make_app("myorg", "quay.io", ["repo-b"])

    result = integration.compile_desired_state(orgs=[org], apps=[app1, app2])
    assert len(result) == 1
    assert result[0].repos is not None
    repo_names = {r.name for r in result[0].repos}
    assert repo_names == {"repo-a", "repo-b"}


def test_compile_desired_state_duplicate_in_different_orgs_ok() -> None:
    integration = _make_integration()
    org1 = _make_org(name="org1", token_path="secret/quay/org1")
    org2 = _make_org(name="org2", token_path="secret/quay/org2")
    app1 = _make_app("org1", "quay.io", ["shared-name"])
    app2 = _make_app("org2", "quay.io", ["shared-name"])

    result = integration.compile_desired_state(orgs=[org1, org2], apps=[app1, app2])
    assert len(result) == 2


# ---------------------------------------------------------------------------
# compile_desired_state — no automationToken → skip org
# ---------------------------------------------------------------------------


def test_compile_desired_state_skips_org_without_token() -> None:
    integration = _make_integration()
    org = _make_org_no_token()
    app = _make_app("myorg", "quay.io", ["some-repo"])

    result = integration.compile_desired_state(orgs=[org], apps=[app])

    assert result == []


def test_compile_desired_state_skips_only_tokenless_org() -> None:
    """Org with token is included; org without token is skipped."""
    integration = _make_integration()
    org_with_token = _make_org(name="org-with-token", token_path="secret/quay/a")
    org_no_token = _make_org_no_token(name="org-no-token")
    app = _make_app("org-with-token", "quay.io", ["repo-a"])

    result = integration.compile_desired_state(
        orgs=[org_with_token, org_no_token], apps=[app]
    )

    assert len(result) == 1
    assert result[0].org_name == "org-with-token"


# ---------------------------------------------------------------------------
# compile_desired_state — mirror-org key construction
# ---------------------------------------------------------------------------


def test_compile_desired_state_mirror_sets_quay_org_key() -> None:
    integration = _make_integration()
    org = _make_org_with_mirror(
        name="myorg",
        mirror_name="upstream-org",
        mirror_instance="quay.io",
    )

    result = integration.compile_desired_state(orgs=[org], apps=[])

    assert len(result) == 1
    assert result[0].mirror == QuayOrgKey(instance="quay.io", org_name="upstream-org")


def test_compile_desired_state_no_mirror_is_none() -> None:
    integration = _make_integration()
    org = _make_org()

    result = integration.compile_desired_state(orgs=[org], apps=[])

    assert result[0].mirror is None


# ---------------------------------------------------------------------------
# reconcile() — calls API client and returns response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_sends_request_and_returns_response() -> None:
    integration = _make_integration()
    org_config = integration.compile_desired_state(orgs=[_make_org()], apps=[])
    fake_response = QuayReposTaskResponse(
        id="task-123",
        status=TaskStatus.PENDING,
        status_url="/api/v1/integrations/quay-repos/reconcile/task-123",
    )

    with patch(
        "reconcile.quay_repos_api.quay_repos_reconcile",
        new_callable=AsyncMock,
        return_value=fake_response,
    ) as mock_reconcile:
        response = await integration.reconcile(orgs=org_config, dry_run=True)

    mock_reconcile.assert_awaited_once()
    called_request = mock_reconcile.call_args[0][0]
    assert called_request.dry_run is True
    assert len(called_request.orgs) == 1
    assert response.id == "task-123"


# ---------------------------------------------------------------------------
# async_run() — integration-level orchestration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_run_no_desired_state_exits_early() -> None:
    integration = _make_integration()

    with (
        patch("reconcile.quay_repos_api.gql") as mock_gql,
        patch.object(integration, "get_quay_orgs", return_value=[]),
        patch.object(integration, "get_apps", return_value=[]),
        patch(
            "reconcile.quay_repos_api.quay_repos_reconcile",
            new_callable=AsyncMock,
        ) as mock_reconcile,
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=True)

    mock_reconcile.assert_not_called()


@pytest.mark.asyncio
async def test_async_run_dry_run_polls_and_logs_actions() -> None:
    integration = _make_integration()
    org = _make_org()
    fake_response = QuayReposTaskResponse(
        id="task-abc",
        status=TaskStatus.PENDING,
        status_url="/api/v1/integrations/quay-repos/reconcile/task-abc",
    )
    fake_result = QuayReposTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[],
        applied_count=0,
        applied_actions=[],
        errors=[],
    )

    with (
        patch("reconcile.quay_repos_api.gql") as mock_gql,
        patch.object(integration, "get_quay_orgs", return_value=[org]),
        patch.object(integration, "get_apps", return_value=[]),
        patch(
            "reconcile.quay_repos_api.quay_repos_reconcile",
            new_callable=AsyncMock,
            return_value=fake_response,
        ) as mock_reconcile,
        patch.object(
            integration,
            "poll_task_status",
            new_callable=AsyncMock,
            return_value=fake_result,
        ) as mock_poll,
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=True)

    mock_reconcile.assert_awaited_once()
    called_request = mock_reconcile.call_args[0][0]
    assert called_request.dry_run is True
    mock_poll.assert_awaited_once_with(
        status_url=fake_response.status_url,
        result_type=QuayReposTaskResult,
    )


@pytest.mark.asyncio
async def test_async_run_non_dry_run_does_not_poll() -> None:
    integration = _make_integration()
    org = _make_org()
    fake_response = QuayReposTaskResponse(
        id="task-xyz",
        status=TaskStatus.PENDING,
        status_url="/api/v1/integrations/quay-repos/reconcile/task-xyz",
    )

    with (
        patch("reconcile.quay_repos_api.gql") as mock_gql,
        patch.object(integration, "get_quay_orgs", return_value=[org]),
        patch.object(integration, "get_apps", return_value=[]),
        patch(
            "reconcile.quay_repos_api.quay_repos_reconcile",
            new_callable=AsyncMock,
            return_value=fake_response,
        ),
        patch.object(
            integration,
            "poll_task_status",
            new_callable=AsyncMock,
        ) as mock_poll,
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=False)

    mock_poll.assert_not_called()
