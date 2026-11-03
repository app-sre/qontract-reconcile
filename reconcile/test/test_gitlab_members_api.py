"""Tests for the gitlab-members-api client-side integration."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qontract_api_client.schemas import (
    EscalationPolicyUsersResponse,
    GitlabMemberActionAdd,
    GitlabMembersInstanceConfig,
    GitlabMembersTaskResponse,
    GitlabMembersTaskResult,
    ScheduleUsersResponse,
    Secret,
    TaskStatus,
)
from qontract_api_client.schemas import (
    PagerDutyUser as PagerDutyUserResponse,
)
from qontract_utils.exceptions import IntegrationError
from qontract_utils.gitlab_api import GitlabAccessLevel

from reconcile.gitlab_members_api import (
    GitlabMembersIntegration,
    GitlabMembersIntegrationParams,
)
from reconcile.gql_definitions.fragments.user import User
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.gitlab_members_api.gitlab_instances import (
    GitlabInstanceV1,
)
from reconcile.gql_definitions.gitlab_members_api.permissions import (
    BotV1,
    PagerDutyInstanceV1,
    PagerDutyTargetV1,
    PermissionGitlabGroupMembershipV1,
    RoleV1,
    UserV1,
)

SECRET_MANAGER_URL = "https://vault.example.com"


class _TestableIntegration(GitlabMembersIntegration):
    @property
    def secret_manager_url(self) -> str:
        return SECRET_MANAGER_URL


def make_integration() -> _TestableIntegration:
    return _TestableIntegration(GitlabMembersIntegrationParams())


def make_vault_secret(
    path: str = "app-sre/creds/gitlab", field: str = "token", version: int = 1
) -> VaultSecret:
    return VaultSecret(path=path, field=field, version=version, format=None, url=None)


def make_gitlab_instance(
    name: str = "gitlab-cee",
    managed_groups: list[str] | None = None,
    ssl_verify: bool | None = True,
) -> GitlabInstanceV1:
    return GitlabInstanceV1(
        name=name,
        description="description",
        url=f"https://{name}.example.com",
        token=make_vault_secret(),
        sslVerify=ssl_verify,
        managedGroups=managed_groups or ["team"],
    )


def make_role(
    name: str = "test-role",
    users: list[str] | None = None,
    bots: list[str | None] | None = None,
) -> RoleV1:
    return RoleV1(
        name=name,
        memberSources=None,
        users=[UserV1(org_username=u) for u in (users or [])],
        bots=[BotV1(org_username=b) for b in (bots or [])],
    )


def make_pagerduty_target(
    schedule_id: str | None = None,
    escalation_policy_id: str | None = None,
    instance_name: str = "redhat",
) -> PagerDutyTargetV1:
    return PagerDutyTargetV1(
        name="pd-target",
        instance=PagerDutyInstanceV1(name=instance_name, token=make_vault_secret()),
        scheduleID=schedule_id,
        escalationPolicyID=escalation_policy_id,
    )


def make_permission(
    group: str = "team",
    access: str = "developer",
    roles: list[RoleV1] | None = None,
    pagerduty: list[PagerDutyTargetV1] | None = None,
) -> PermissionGitlabGroupMembershipV1:
    return PermissionGitlabGroupMembershipV1(
        name="perm",
        group=group,
        access=access,
        pagerduty=pagerduty,
        roles=roles,
    )


def make_user(org_username: str, pagerduty_username: str | None = None) -> User:
    return User(
        name=org_username,
        org_username=org_username,
        github_username=org_username,
        pagerduty_username=pagerduty_username,
        tag_on_merge_requests=None,
        gov_slack_email_local_part=None,
    )


# ---------------------------------------------------------------------------
# get_gitlab_instance
# ---------------------------------------------------------------------------


def test_get_gitlab_instance_returns_single_instance() -> None:
    instance = make_gitlab_instance()
    mock_query = MagicMock(
        return_value={"instances": [instance.model_dump(by_alias=True)]}
    )

    result = GitlabMembersIntegration.get_gitlab_instance(mock_query)

    assert result.name == "gitlab-cee"


def test_get_gitlab_instance_raises_when_none_found() -> None:
    mock_query = MagicMock(return_value={"instances": []})

    with pytest.raises(Exception, match="No gitlab instance found"):
        GitlabMembersIntegration.get_gitlab_instance(mock_query)


def test_get_gitlab_instance_raises_when_multiple_found() -> None:
    instances = [make_gitlab_instance("a"), make_gitlab_instance("b")]
    mock_query = MagicMock(
        return_value={"instances": [i.model_dump(by_alias=True) for i in instances]}
    )

    with pytest.raises(Exception, match="More than one gitlab instance found"):
        GitlabMembersIntegration.get_gitlab_instance(mock_query)


# ---------------------------------------------------------------------------
# get_permissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_permissions_filters_by_managed_groups_and_resolves_roles() -> None:
    query_func = MagicMock()
    queried_role = make_role(name="team-role", users=[])
    resolved_role = make_role(name="team-role", users=["alice"])
    permissions = [
        make_permission(group="team", roles=[queried_role]),
        make_permission(group="other-team", roles=[queried_role]),
    ]

    with (
        patch(
            "reconcile.gitlab_members_api._query_permissions",
            return_value=permissions,
        ),
        patch(
            "reconcile.gitlab_members_api.resolve_role_members",
            new=AsyncMock(return_value=[resolved_role]),
        ) as mock_resolve,
    ):
        result = await GitlabMembersIntegration.get_permissions(
            query_func, managed_groups=["team"]
        )

    assert [p.group for p in result] == ["team"]
    assert result[0].roles == [resolved_role]
    mock_resolve.assert_awaited_once()
    assert mock_resolve.call_args.kwargs["user_cls"] is UserV1
    assert mock_resolve.call_args.kwargs["query_func"] is query_func


# ---------------------------------------------------------------------------
# compile_group_members
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compile_group_members_from_role_users() -> None:
    integration = make_integration()
    permissions = [
        make_permission(
            group="team", access="developer", roles=[make_role(users=["alice"])]
        )
    ]

    result = await integration.compile_group_members("team", permissions, [])

    assert len(result) == 1
    assert result[0].username == "alice"
    assert result[0].access_level == GitlabAccessLevel.DEVELOPER


@pytest.mark.asyncio
async def test_compile_group_members_includes_bots() -> None:
    integration = make_integration()
    permissions = [
        make_permission(
            group="team",
            access="maintainer",
            roles=[make_role(users=["alice"], bots=["bot-user"])],
        )
    ]

    result = await integration.compile_group_members("team", permissions, [])

    usernames = {m.username for m in result}
    assert usernames == {"alice", "bot-user"}
    assert all(m.access_level == GitlabAccessLevel.MAINTAINER for m in result)


@pytest.mark.asyncio
async def test_compile_group_members_bot_without_org_username_is_skipped() -> None:
    integration = make_integration()
    permissions = [
        make_permission(
            group="team",
            roles=[make_role(users=["alice"], bots=[None])],
        )
    ]

    result = await integration.compile_group_members("team", permissions, [])

    assert [m.username for m in result] == ["alice"]


@pytest.mark.asyncio
async def test_compile_group_members_highest_access_level_wins() -> None:
    integration = make_integration()
    permissions = [
        make_permission(
            group="team", access="developer", roles=[make_role(users=["alice"])]
        ),
        make_permission(
            group="team", access="maintainer", roles=[make_role(users=["alice"])]
        ),
    ]

    result = await integration.compile_group_members("team", permissions, [])

    assert len(result) == 1
    assert result[0].access_level == GitlabAccessLevel.MAINTAINER


@pytest.mark.asyncio
async def test_compile_group_members_ignores_other_groups() -> None:
    integration = make_integration()
    permissions = [
        make_permission(group="other-team", roles=[make_role(users=["alice"])])
    ]

    result = await integration.compile_group_members("team", permissions, [])

    assert result == []


@pytest.mark.asyncio
async def test_compile_group_members_includes_pagerduty_users() -> None:
    integration = make_integration()
    permissions = [
        make_permission(
            group="team",
            access="reporter",
            pagerduty=[make_pagerduty_target(schedule_id="SCHED1")],
        )
    ]
    users = [make_user("alice")]

    with patch.object(
        integration,
        "compile_users_from_pagerduty",
        new=AsyncMock(return_value=["alice"]),
    ):
        result = await integration.compile_group_members("team", permissions, users)

    assert len(result) == 1
    assert result[0].username == "alice"
    assert result[0].access_level == GitlabAccessLevel.REPORTER


# ---------------------------------------------------------------------------
# compile_users_from_pagerduty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compile_users_from_pagerduty_returns_empty_when_no_targets() -> None:
    integration = make_integration()

    result = await integration.compile_users_from_pagerduty(None, [], "team")

    assert result == []


@pytest.mark.asyncio
async def test_compile_users_from_pagerduty_schedule_translates_username() -> None:
    integration = make_integration()
    pagerduties = [make_pagerduty_target(schedule_id="SCHED1")]
    users = [make_user("alice", pagerduty_username="alice-pd")]

    with patch(
        "reconcile.gitlab_members_api.pagerduty_schedule_users",
        new=AsyncMock(
            return_value=ScheduleUsersResponse(
                users=[PagerDutyUserResponse(username="alice-pd")]
            )
        ),
    ):
        result = await integration.compile_users_from_pagerduty(
            pagerduties, users, "team"
        )

    assert result == ["alice"]


@pytest.mark.asyncio
async def test_compile_users_from_pagerduty_escalation_policy_translates_username() -> (
    None
):
    integration = make_integration()
    pagerduties = [make_pagerduty_target(escalation_policy_id="POLICY1")]
    users = [make_user("alice", pagerduty_username="alice-pd")]

    with patch(
        "reconcile.gitlab_members_api.pagerduty_escalation_policy_users",
        new=AsyncMock(
            return_value=EscalationPolicyUsersResponse(
                users=[PagerDutyUserResponse(username="alice-pd")]
            )
        ),
    ):
        result = await integration.compile_users_from_pagerduty(
            pagerduties, users, "team"
        )

    assert result == ["alice"]


@pytest.mark.asyncio
async def test_compile_users_from_pagerduty_matches_by_org_username_fallback() -> None:
    """A user with no pagerduty_username override is matched by org_username."""
    integration = make_integration()
    pagerduties = [make_pagerduty_target(schedule_id="SCHED1")]
    users = [make_user("alice")]

    with patch(
        "reconcile.gitlab_members_api.pagerduty_schedule_users",
        new=AsyncMock(
            return_value=ScheduleUsersResponse(
                users=[PagerDutyUserResponse(username="alice")]
            )
        ),
    ):
        result = await integration.compile_users_from_pagerduty(
            pagerduties, users, "team"
        )

    assert result == ["alice"]


@pytest.mark.asyncio
async def test_compile_users_from_pagerduty_drops_unknown_username_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    integration = make_integration()
    pagerduties = [make_pagerduty_target(schedule_id="SCHED1")]
    users: list[User] = []

    with patch(
        "reconcile.gitlab_members_api.pagerduty_schedule_users",
        new=AsyncMock(
            return_value=ScheduleUsersResponse(
                users=[PagerDutyUserResponse(username="bob")]
            )
        ),
    ):
        result = await integration.compile_users_from_pagerduty(
            pagerduties, users, "team"
        )

    assert result == []
    assert "bob" in caplog.text
    assert "team" in caplog.text


@pytest.mark.asyncio
async def test_compile_users_from_pagerduty_raises_for_misconfigured_target() -> None:
    integration = make_integration()
    pagerduties = [make_pagerduty_target()]

    with pytest.raises(IntegrationError, match="pd-target"):
        await integration.compile_users_from_pagerduty(pagerduties, [], "team")


# ---------------------------------------------------------------------------
# compile_desired_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compile_desired_state_builds_instance_config() -> None:
    integration = make_integration()
    instance = make_gitlab_instance(managed_groups=["team-a", "team-b"])
    permissions = [
        make_permission(group="team-a", roles=[make_role(users=["alice"])]),
    ]

    result = await integration.compile_desired_state(instance, permissions, [])

    assert result.name == "gitlab-cee"
    assert result.url == instance.url
    assert result.ssl_verify is True
    assert result.token.secret_manager_url == SECRET_MANAGER_URL
    assert result.token.path == instance.token.path
    assert result.groups is not None
    assert [g.group for g in result.groups] == ["team-a", "team-b"]
    assert [m.username for m in result.groups[0].members or []] == ["alice"]
    assert result.groups[1].members == []


@pytest.mark.asyncio
async def test_compile_desired_state_defaults_null_ssl_verify_to_true() -> None:
    integration = make_integration()
    instance = make_gitlab_instance(ssl_verify=None)

    result = await integration.compile_desired_state(instance, [], [])

    assert result.ssl_verify is True


# ---------------------------------------------------------------------------
# async_run
# ---------------------------------------------------------------------------


def _make_task_response(task_id: str = "task-123") -> GitlabMembersTaskResponse:
    return GitlabMembersTaskResponse(
        id=task_id, status=TaskStatus.PENDING, status_url=f"/tasks/{task_id}"
    )


def _make_task_result(
    status: TaskStatus = TaskStatus.SUCCESS,
    actions: list | None = None,
    errors: list | None = None,
) -> GitlabMembersTaskResult:
    return GitlabMembersTaskResult(
        status=status,
        actions=actions or [],
        errors=errors or [],
    )


def _make_desired_instance() -> GitlabMembersInstanceConfig:
    return GitlabMembersInstanceConfig(
        name="gitlab-cee",
        url="https://gitlab-cee.example.com",
        ssl_verify=True,
        token=Secret(
            secret_manager_url=SECRET_MANAGER_URL, path="p", field="f", version=1
        ),
        groups=[],
    )


@pytest.mark.asyncio
async def test_dry_run_waits_for_task_and_logs_actions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    integration = make_integration()
    task_response = _make_task_response()
    action = GitlabMemberActionAdd(
        instance="gitlab-cee",
        group="team",
        username="alice",
        user_id=1,
        access_level=GitlabAccessLevel.DEVELOPER,
    )
    task_result = _make_task_result(actions=[action])

    with (
        patch("reconcile.gitlab_members_api.gql") as mock_gql,
        patch.object(
            integration, "get_gitlab_instance", return_value=make_gitlab_instance()
        ),
        patch.object(
            GitlabMembersIntegration, "get_permissions", new=AsyncMock(return_value=[])
        ),
        patch("reconcile.gitlab_members_api.get_users", return_value=[]),
        patch.object(
            integration,
            "compile_desired_state",
            new=AsyncMock(return_value=_make_desired_instance()),
        ),
        patch(
            "reconcile.gitlab_members_api.reconcile_gitlab_members",
            new=AsyncMock(return_value=task_response),
        ) as mock_reconcile,
        patch.object(
            integration, "poll_task_status", new=AsyncMock(return_value=task_result)
        ) as mock_poll,
        caplog.at_level(logging.INFO),
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=True)

    mock_reconcile.assert_awaited_once()
    mock_poll.assert_awaited_once()
    assert "action.action_type='add_member'" in caplog.text
    assert "action.group='team'" in caplog.text
    assert "action.username='alice'" in caplog.text


@pytest.mark.asyncio
async def test_non_dry_run_does_not_wait_for_task() -> None:
    integration = make_integration()
    task_response = _make_task_response()

    with (
        patch("reconcile.gitlab_members_api.gql") as mock_gql,
        patch.object(
            integration, "get_gitlab_instance", return_value=make_gitlab_instance()
        ),
        patch.object(
            GitlabMembersIntegration, "get_permissions", new=AsyncMock(return_value=[])
        ),
        patch("reconcile.gitlab_members_api.get_users", return_value=[]),
        patch.object(
            integration,
            "compile_desired_state",
            new=AsyncMock(return_value=_make_desired_instance()),
        ),
        patch(
            "reconcile.gitlab_members_api.reconcile_gitlab_members",
            new=AsyncMock(return_value=task_response),
        ),
        patch.object(integration, "poll_task_status") as mock_status,
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=False)
        mock_status.assert_not_called()


@pytest.mark.asyncio
async def test_dry_run_exits_with_errors() -> None:
    integration = make_integration()
    task_response = _make_task_response()
    task_result = _make_task_result(errors=["something went wrong"])

    with (
        patch("reconcile.gitlab_members_api.gql") as mock_gql,
        patch.object(
            integration, "get_gitlab_instance", return_value=make_gitlab_instance()
        ),
        patch.object(
            GitlabMembersIntegration, "get_permissions", new=AsyncMock(return_value=[])
        ),
        patch("reconcile.gitlab_members_api.get_users", return_value=[]),
        patch.object(
            integration,
            "compile_desired_state",
            new=AsyncMock(return_value=_make_desired_instance()),
        ),
        patch(
            "reconcile.gitlab_members_api.reconcile_gitlab_members",
            new=AsyncMock(return_value=task_response),
        ),
        patch.object(
            integration, "poll_task_status", new=AsyncMock(return_value=task_result)
        ),
        pytest.raises(IntegrationError),
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=True)


@pytest.mark.asyncio
async def test_dry_run_exits_on_timeout() -> None:
    integration = make_integration()
    task_response = _make_task_response()
    task_result = _make_task_result(status=TaskStatus.PENDING)

    with (
        patch("reconcile.gitlab_members_api.gql") as mock_gql,
        patch.object(
            integration, "get_gitlab_instance", return_value=make_gitlab_instance()
        ),
        patch.object(
            GitlabMembersIntegration, "get_permissions", new=AsyncMock(return_value=[])
        ),
        patch("reconcile.gitlab_members_api.get_users", return_value=[]),
        patch.object(
            integration,
            "compile_desired_state",
            new=AsyncMock(return_value=_make_desired_instance()),
        ),
        patch(
            "reconcile.gitlab_members_api.reconcile_gitlab_members",
            new=AsyncMock(return_value=task_response),
        ),
        patch.object(
            integration, "poll_task_status", new=AsyncMock(return_value=task_result)
        ),
        pytest.raises(IntegrationError),
    ):
        mock_gql.get_api.return_value = MagicMock()
        await integration.async_run(dry_run=True)
