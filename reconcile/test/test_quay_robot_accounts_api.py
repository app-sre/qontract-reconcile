"""Tests for the quay-robot-accounts-api client-side integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qontract_api_client.schemas import (
    QuayRobotAccountsTaskResponse,
    QuayRobotAccountsTaskResult,
    QuayRobotActionCreate,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.quay_robot_accounts_api.quay_robot_accounts import (
    QuayInstanceV1,
    QuayOrgV1,
    QuayRepositoryV1,
    QuayRobotV1,
)
from reconcile.quay_robot_accounts_api import (
    QuayRobotAccountsIntegration,
    QuayRobotAccountsIntegrationParams,
)

SECRET_MANAGER_URL = "https://vault.example.com"


class _TestableIntegration(QuayRobotAccountsIntegration):
    @property
    def secret_manager_url(self) -> str:
        return SECRET_MANAGER_URL


def make_integration(org_name: str | None = None) -> _TestableIntegration:
    return _TestableIntegration(QuayRobotAccountsIntegrationParams(org_name=org_name))


def make_vault_secret(
    path: str = "app-sre/creds/quay", field: str = "token", version: int = 1
) -> VaultSecret:
    return VaultSecret(path=path, field=field, version=version, format=None)


def make_org(
    name: str = "test-org",
    *,
    has_token: bool = True,
    managed_teams: list[str] | None = None,
    managed_repos: bool = True,
    managed_robot_accounts: bool = True,
) -> QuayOrgV1:
    return QuayOrgV1(
        name=name,
        managedTeams=managed_teams if managed_teams is not None else ["team1"],
        managedRepos=managed_repos,
        managedRobotAccounts=managed_robot_accounts,
        instance=QuayInstanceV1(name="quay-io", url="quay.io"),
        automationToken=make_vault_secret() if has_token else None,
    )


def make_robot(
    name: str = "ci-bot",
    org: QuayOrgV1 | None = None,
    *,
    teams: list[str] | None = None,
    repositories: list[QuayRepositoryV1] | None = None,
    delete: bool | None = None,
    description: str | None = "CI",
) -> QuayRobotV1:
    return QuayRobotV1(
        name=name,
        description=description,
        quay_org=org if org is not None else make_org(),
        teams=teams if teams is not None else ["team1"],
        repositories=repositories
        if repositories is not None
        else [QuayRepositoryV1(name="repo1", permission="read")],
        delete=delete,
    )


def test_compile_desired_state_groups_robots_by_org() -> None:
    org = make_org()
    robots = [
        make_robot("bot-a", org),
        make_robot("bot-b", org, teams=["team1"], repositories=[]),
    ]
    integration = make_integration()

    desired = integration.compile_desired_state(robots)

    assert len(desired) == 1
    assert desired[0].org_name == "test-org"
    assert desired[0].instance_name == "quay-io"
    assert [r.name for r in desired[0].robots or []] == ["bot-a", "bot-b"]
    assert desired[0].token.path == "app-sre/creds/quay"
    assert desired[0].token.secret_manager_url == SECRET_MANAGER_URL
    assert desired[0].managed_teams == ["team1"]
    assert desired[0].managed_repos is True
    assert desired[0].managed_robot_accounts is True


def test_compile_desired_state_skips_robot_without_org() -> None:
    robot = QuayRobotV1(
        name="orphan",
        description=None,
        quay_org=None,
        teams=[],
        repositories=[],
        delete=None,
    )
    desired = make_integration().compile_desired_state([robot])
    assert desired == []


def test_compile_desired_state_org_filter() -> None:
    org_a = make_org("org-a")
    org_b = make_org("org-b")
    robots = [make_robot("a", org_a), make_robot("b", org_b)]
    desired = make_integration(org_name="org-b").compile_desired_state(
        robots, org_name_filter="org-b"
    )
    assert len(desired) == 1
    assert desired[0].org_name == "org-b"


def test_compile_desired_state_missing_token_fails_closed() -> None:
    org = make_org(has_token=False)
    robots = [make_robot("bot", org)]
    with pytest.raises(IntegrationError, match="automationToken"):
        make_integration().compile_desired_state(robots)


@pytest.mark.asyncio
async def test_async_run_dry_run_polls_and_logs() -> None:
    integration = make_integration()
    robots = [make_robot()]
    task = QuayRobotAccountsTaskResponse(
        id="task-1",
        status=TaskStatus.PENDING,
        status_url="http://api/status/task-1",
    )
    result = QuayRobotAccountsTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[
            QuayRobotActionCreate(
                instance_name="quay-io",
                org_name="test-org",
                robot_name="ci-bot",
            )
        ],
        applied_count=0,
        errors=[],
    )

    with (
        patch("reconcile.quay_robot_accounts_api.gql") as mock_gql,
        patch.object(integration, "get_robot_accounts", return_value=robots),
        patch.object(
            integration, "reconcile", new_callable=AsyncMock, return_value=task
        ) as mock_reconcile,
        patch.object(
            integration, "poll_task_status", new_callable=AsyncMock, return_value=result
        ) as mock_poll,
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=True)

    mock_reconcile.assert_awaited_once()
    assert mock_reconcile.await_args.kwargs["dry_run"] is True
    mock_poll.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_run_apply_is_fire_and_forget() -> None:
    integration = make_integration()
    robots = [make_robot()]
    task = QuayRobotAccountsTaskResponse(
        id="task-1",
        status=TaskStatus.PENDING,
        status_url="http://api/status/task-1",
    )

    with (
        patch("reconcile.quay_robot_accounts_api.gql") as mock_gql,
        patch.object(integration, "get_robot_accounts", return_value=robots),
        patch.object(
            integration, "reconcile", new_callable=AsyncMock, return_value=task
        ),
        patch.object(
            integration, "poll_task_status", new_callable=AsyncMock
        ) as mock_poll,
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=False)

    mock_poll.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_run_raises_on_task_errors() -> None:
    integration = make_integration()
    robots = [make_robot()]
    task = QuayRobotAccountsTaskResponse(
        id="task-1",
        status=TaskStatus.PENDING,
        status_url="http://api/status/task-1",
    )
    result = QuayRobotAccountsTaskResult(
        status=TaskStatus.FAILED,
        actions=[],
        applied_count=0,
        errors=["test-org: boom"],
    )

    with (
        patch("reconcile.quay_robot_accounts_api.gql") as mock_gql,
        patch.object(integration, "get_robot_accounts", return_value=robots),
        patch.object(
            integration, "reconcile", new_callable=AsyncMock, return_value=task
        ),
        patch.object(
            integration, "poll_task_status", new_callable=AsyncMock, return_value=result
        ),
        pytest.raises(IntegrationError, match="boom"),
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=True)


@pytest.mark.asyncio
async def test_async_run_no_desired_state_returns() -> None:
    integration = make_integration()
    with (
        patch("reconcile.quay_robot_accounts_api.gql") as mock_gql,
        patch.object(integration, "get_robot_accounts", return_value=[]),
        patch.object(
            integration, "reconcile", new_callable=AsyncMock
        ) as mock_reconcile,
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=True)
    mock_reconcile.assert_not_awaited()
