"""Tests for the slack-usergroups-api client-side integration.

Covers the standalone helpers, the desired-state compilation from every user
source (roles, schedules, git OWNERS files, PagerDuty, GitHub org members,
cluster access), permission processing, workspace assembly, and the async_run
orchestration (dry-run vs apply, polling, error handling).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qontract_api_client.schemas import (
    EscalationPolicyUsersResponse,
    GithubOrgMembersResponse,
    LdapGithubUser,
    LdapGithubUsernamesResponse,
    LdapGroupMember,
    LdapGroupMembersResponse,
    LdapGroupResult,
    PagerDutyUser,
    RepoOwnersResponse,
    ScheduleUsersResponse,
    SlackUsergroup,
    SlackUsergroupActionCreate,
    SlackUsergroupActionUpdateMetadata,
    SlackUsergroupActionUpdateUsers,
    SlackUsergroupConfig,
    SlackUsergroupsTaskResponse,
    SlackUsergroupsTaskResult,
    TaskStatus,
    VCSProvider,
)
from qontract_utils.vcs import Provider

from reconcile.gql_definitions.common.ldap_settings import LdapSettingsV1
from reconcile.gql_definitions.fragments.membership_source import (
    MembershipProviderSourceV1,
    MembershipProviderV1,
    RoleMembershipSource,
)
from reconcile.gql_definitions.fragments.user import User
from reconcile.gql_definitions.fragments.vault_secret import (
    VaultSecret as LdapVaultSecret,
)
from reconcile.gql_definitions.slack_usergroups_api.clusters import (
    ClusterV1 as EnabledClusterV1,
)
from reconcile.gql_definitions.slack_usergroups_api.clusters import (
    DisableClusterAutomationsV1,
)
from reconcile.gql_definitions.slack_usergroups_api.permissions import (
    BotV1,
    GithubOrgV1,
    PagerDutyInstanceV1,
    PagerDutyTargetV1,
    PermissionSlackUsergroupV1,
    RoleV1,
    ScheduleEntryV1,
    ScheduleV1,
    SlackUsergroupNotificationV1,
    SlackWorkspaceIntegrationV1,
    SlackWorkspaceV1,
    VaultSecret,
)
from reconcile.gql_definitions.slack_usergroups_api.roles import (
    AccessV1,
    NamespaceV1,
    NamespaceV1_ClusterV1,
)
from reconcile.gql_definitions.slack_usergroups_api.roles import (
    ClusterV1 as AccessClusterV1,
)
from reconcile.gql_definitions.slack_usergroups_api.roles import (
    RoleV1 as ClusterAccessRole,
)
from reconcile.gql_definitions.slack_usergroups_api.roles import (
    UserV1 as ClusterAccessUser,
)
from reconcile.gql_definitions.slack_usergroups_api.users import UserV1
from reconcile.slack_usergroups_api import (
    QONTRACT_INTEGRATION,
    SlackUsergroupPermission,
    SlackUsergroupsIntegration,
    SlackUsergroupsIntegrationParams,
    SlackWorkspace,
    get_token_from_url,
)
from reconcile.typed_queries.vcs import Vcs

if TYPE_CHECKING:
    from collections.abc import Generator

    from pytest_mock import MockerFixture

_MOD = "reconcile.slack_usergroups_api"
_LDAP_RESOLVER_MOD = "reconcile.utils.membershipsources.ldap_resolver"


# --- factories ---


def _vault_secret(path: str = "secret/token", field: str = "token") -> VaultSecret:
    return VaultSecret(path=path, field=field, version=None, format=None, url=None)


def _frag_user(
    org_username: str,
    *,
    github_username: str = "",
    pagerduty_username: str | None = None,
    tag_on_merge_requests: bool | None = None,
    gov_slack_email_local_part: str | None = None,
) -> User:
    return User(
        name=org_username,
        org_username=org_username,
        github_username=github_username or f"{org_username}-gh",
        pagerduty_username=pagerduty_username,
        tag_on_merge_requests=tag_on_merge_requests,
        gov_slack_email_local_part=gov_slack_email_local_part,
    )


def _app_user(
    org_username: str,
    github_username: str,
    *,
    pagerduty_username: str | None = None,
    tag_on_merge_requests: bool | None = None,
    gov_slack_email_local_part: str | None = None,
    tag_on_cluster_updates: bool | None = None,
) -> UserV1:
    return UserV1(
        name=org_username,
        org_username=org_username,
        github_username=github_username,
        pagerduty_username=pagerduty_username,
        tag_on_merge_requests=tag_on_merge_requests,
        gov_slack_email_local_part=gov_slack_email_local_part,
        tag_on_cluster_updates=tag_on_cluster_updates,
        roles=None,
    )


def _cluster_user(
    org_username: str,
    *,
    tag_on_cluster_updates: bool | None = None,
) -> ClusterAccessUser:
    return ClusterAccessUser(
        name=org_username,
        org_username=org_username,
        github_username=f"{org_username}-gh",
        pagerduty_username=None,
        tag_on_merge_requests=None,
        gov_slack_email_local_part=None,
        tag_on_cluster_updates=tag_on_cluster_updates,
    )


def _role(
    *,
    name: str = "role",
    users: list[User] | None = None,
    bots: list[BotV1] | None = None,
    member_sources: list[RoleMembershipSource] | None = None,
) -> RoleV1:
    return RoleV1(
        name=name,
        users=users or [],
        bots=bots or [],
        memberSources=member_sources,
    )


def _ldap_membership_source(
    *, name: str = "corp-ldap", group: str = "team-a"
) -> RoleMembershipSource:
    return RoleMembershipSource(
        provider=MembershipProviderV1(
            name=name,
            hasAuditTrail=False,
            source=MembershipProviderSourceV1(provider="ldap"),
        ),
        group=group,
    )


def _github_org() -> GithubOrgV1:
    return GithubOrgV1(name="my-org", token=_vault_secret("secret/github/token"))


def _ldap_settings(*, with_credentials: bool = True) -> LdapSettingsV1:
    return LdapSettingsV1(
        serverUrl="ldap://freeipa.example.com",
        baseDn="dc=example,dc=com",
        credentials=LdapVaultSecret(
            path="secret/ldap/bind",
            field="password",
            version=None,
            format=None,
            url=None,
        )
        if with_credentials
        else None,
    )


def _workspace(
    *,
    name: str = "coreos",
    managed: list[str] | None = None,
    with_integration: bool = True,
) -> SlackWorkspaceV1:
    integrations = None
    if with_integration:
        integrations = [
            SlackWorkspaceIntegrationV1(
                name="slack-usergroups",
                token=_vault_secret("secret/slack/token"),
                channel="#general",
            )
        ]
    return SlackWorkspaceV1(
        path="/dependencies/slack/coreos.yml",
        name=name,
        integrations=integrations,
        managedUsergroups=managed if managed is not None else ["team-handle"],
    )


def _permission(
    *,
    handle: str = "team-handle",
    skip: bool | None = None,
    roles: list[RoleV1] | None = None,
    schedule: ScheduleV1 | None = None,
    pagerduty: list[PagerDutyTargetV1] | None = None,
    github: GithubOrgV1 | None = None,
    owners_from_repos: list[str] | None = None,
    notifications: list[SlackUsergroupNotificationV1] | None = None,
    channels: list[str] | None = None,
    workspace: SlackWorkspaceV1 | None = None,
) -> PermissionSlackUsergroupV1:
    return PermissionSlackUsergroupV1(
        service="slack-usergroup",
        channels=channels if channels is not None else ["#team"],
        description="Team handle",
        handle=handle,
        notifications=notifications,
        ownersFromRepos=owners_from_repos,
        skip=skip,
        pagerduty=pagerduty,
        github=github,
        roles=roles,
        schedule=schedule,
        workspace=workspace or _workspace(managed=[handle]),
    )


def _resolved_permission(
    permission: PermissionSlackUsergroupV1,
) -> SlackUsergroupPermission:
    return SlackUsergroupPermission.model_validate(
        permission.model_dump(), by_name=True
    )


@pytest.fixture
def integration() -> Generator[SlackUsergroupsIntegration]:
    inst = SlackUsergroupsIntegration(
        SlackUsergroupsIntegrationParams(workspace_name=None, usergroup_name=None)
    )
    with patch.object(
        type(inst),
        "secret_manager_url",
        new_callable=lambda: property(lambda self: "https://vault.example.com"),
    ):
        yield inst


@pytest.fixture
def permission_query(mocker: MockerFixture) -> MagicMock:
    return mocker.patch(f"{_MOD}.permissions_query")


# --- get_token_from_url ---


def _vcs(name: str, url: str, provider: Provider, *, default: bool = False) -> Vcs:
    return Vcs(
        name=name,
        url=url,
        default=default,
        token=_vault_secret(f"secret/{name}"),
        provider=provider,
    )


def test_get_token_from_url_github_exact_match() -> None:
    from qontract_utils.vcs import get_default_registry

    instances = [
        _vcs("app-sre", "https://github.com/app-sre", Provider.GITHUB),
        _vcs("other", "https://github.com/other", Provider.GITHUB),
    ]
    token = get_token_from_url(
        get_default_registry(),
        instances,
        "https://github.com/app-sre/qontract-reconcile",
    )
    assert token.path == "secret/app-sre"


def test_get_token_from_url_github_default_fallback() -> None:
    from qontract_utils.vcs import get_default_registry

    instances = [
        _vcs(
            "default-gh", "https://github.com/somewhere", Provider.GITHUB, default=True
        ),
    ]
    token = get_token_from_url(
        get_default_registry(),
        instances,
        "https://github.com/unknown-org/repo",
    )
    assert token.path == "secret/default-gh"


def test_get_token_from_url_gitlab_match() -> None:
    from qontract_utils.vcs import get_default_registry

    instances = [
        _vcs("gitlab", "https://gitlab.cee.redhat.com", Provider.GITLAB),
    ]
    token = get_token_from_url(
        get_default_registry(),
        instances,
        "https://gitlab.cee.redhat.com/service/app-interface",
    )
    assert token.path == "secret/gitlab"


def test_get_token_from_url_no_match_raises() -> None:
    from qontract_utils.vcs import get_default_registry

    # gitlab provider has no default fallback and no instance matches the owner URL
    with pytest.raises(ValueError, match="No matching VCS instance"):
        get_token_from_url(
            get_default_registry(),
            [],
            "https://gitlab.cee.redhat.com/service/other",
        )


# --- name + static getters ---


def test_integration_name(integration: SlackUsergroupsIntegration) -> None:
    assert integration.name == QONTRACT_INTEGRATION == "slack-usergroups-api"


@pytest.mark.asyncio
async def test_get_permissions_filters_slack_usergroup_type(
    integration: SlackUsergroupsIntegration,
) -> None:
    slack_perm = _permission()
    other_perm = MagicMock()  # a non-slack PermissionV1
    query_result = MagicMock()
    query_result.permissions = [slack_perm, other_perm]
    with patch(f"{_MOD}.permissions_query", return_value=query_result):
        result = await integration.get_permissions(query_func=MagicMock())
    assert [permission.handle for permission in result] == [slack_perm.handle]


@pytest.mark.asyncio
async def test_get_permissions_empty(integration: SlackUsergroupsIntegration) -> None:
    query_result = MagicMock()
    query_result.permissions = []
    with patch(f"{_MOD}.permissions_query", return_value=query_result):
        assert await integration.get_permissions(query_func=MagicMock()) == []


def test_get_users() -> None:
    users = [_app_user("alice", "alice-gh")]
    query_result = MagicMock()
    query_result.users = users
    with patch(f"{_MOD}.users_query", return_value=query_result):
        assert SlackUsergroupsIntegration.get_users(MagicMock()) == users


def test_get_clusters_filters_disabled() -> None:
    enabled = EnabledClusterV1(name="enabled", auth=[], disable=None)
    disabled = EnabledClusterV1(
        name="disabled",
        auth=[],
        disable=DisableClusterAutomationsV1(integrations=["slack-usergroups"]),
    )
    query_result = MagicMock()
    query_result.clusters = [enabled, disabled]
    with patch(f"{_MOD}.clusters_query", return_value=query_result):
        result = SlackUsergroupsIntegration.get_clusters(MagicMock())
    assert [c.name for c in result] == ["enabled"]


@pytest.mark.asyncio
async def test_get_roles_filters_expired(
    integration: SlackUsergroupsIntegration,
) -> None:
    active = ClusterAccessRole(
        name="active",
        access=[
            AccessV1(
                cluster=AccessClusterV1(name="prod", auth=[]),
                group="admins",
                namespace=None,
            )
        ],
        expirationDate=None,
        memberSources=None,
        users=[],
        tag_on_cluster_updates=None,
    )
    expired = ClusterAccessRole(
        name="expired",
        access=None,
        expirationDate="2000-01-01",
        memberSources=None,
        users=[],
        tag_on_cluster_updates=None,
    )
    query_result = MagicMock()
    query_result.roles = [active, expired]
    with patch(f"{_MOD}.roles_query", return_value=query_result):
        result = await integration.get_roles(query_func=MagicMock())
    assert [r.name for r in result] == ["active"]


# --- compile_users_from_schedule ---


def test_compile_users_from_schedule_none() -> None:
    assert SlackUsergroupsIntegration.compile_users_from_schedule(None) == []


def test_compile_users_from_schedule_active_window() -> None:
    schedule = ScheduleV1(
        schedule=[
            ScheduleEntryV1(
                start="2000-01-01 00:00",
                end="2100-01-01 00:00",
                users=[_frag_user("alice"), _frag_user("bob")],
            )
        ]
    )
    result = SlackUsergroupsIntegration.compile_users_from_schedule(schedule)
    assert sorted(result) == ["alice", "bob"]


def test_compile_users_from_schedule_inactive_window() -> None:
    schedule = ScheduleV1(
        schedule=[
            ScheduleEntryV1(
                start="2000-01-01 00:00",
                end="2000-01-02 00:00",
                users=[_frag_user("alice")],
            )
        ]
    )
    assert SlackUsergroupsIntegration.compile_users_from_schedule(schedule) == []


# --- compile_users_from_roles ---


def test_compile_users_from_roles_none(
    integration: SlackUsergroupsIntegration,
) -> None:
    assert integration.compile_users_from_roles(None) == []


def test_compile_users_from_roles(
    integration: SlackUsergroupsIntegration,
) -> None:
    roles = [
        _role(
            name="role1",
            users=[_frag_user("alice", gov_slack_email_local_part="alice.gov")],
        ),
        _role(name="role2", users=[_frag_user("bob")]),
    ]
    result = integration.compile_users_from_roles(roles)
    assert sorted(result) == ["alice", "bob"]


def test_compile_users_from_roles_without_member_sources_skips_ldap_call(
    integration: SlackUsergroupsIntegration,
) -> None:
    """Roles without memberSources never hit the LDAP endpoint."""
    roles = [_role(users=[_frag_user("alice")])]
    with patch(
        f"{_LDAP_RESOLVER_MOD}.ldap_group_members", new_callable=AsyncMock
    ) as mock_client:
        result = integration.compile_users_from_roles(roles)

    assert result == ["alice"]
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_compile_users_from_roles_resolves_ldap_source(
    integration: SlackUsergroupsIntegration,
    permission_query: MagicMock,
) -> None:
    roles = [
        _role(
            users=[_frag_user("alice")],
            member_sources=[_ldap_membership_source()],
        )
    ]
    with patch(
        f"{_LDAP_RESOLVER_MOD}.ldap_group_members", new_callable=AsyncMock
    ) as mock_client:
        mock_client.return_value = LdapGroupMembersResponse(
            groups=[
                LdapGroupResult(
                    group="team-a",
                    members=[LdapGroupMember(name="bob", org_username="bob")],
                )
            ]
        )
        permission_query.return_value.permissions = [_permission(roles=roles)]
        permissions = await integration.get_permissions(
            query_func=MagicMock(), ldap_settings=_ldap_settings()
        )
        result = integration.compile_users_from_roles(permissions[0].roles)

    assert sorted(result) == ["alice", "bob"]


@pytest.mark.asyncio
async def test_compile_users_from_roles_dedup_uses_canonical_username(
    integration: SlackUsergroupsIntegration,
    permission_query: MagicMock,
) -> None:
    """Explicit and LDAP duplicates remain one canonical identity."""
    roles = [
        _role(
            users=[_frag_user("shared", gov_slack_email_local_part="shared.gov")],
            member_sources=[_ldap_membership_source()],
        )
    ]
    with patch(
        f"{_LDAP_RESOLVER_MOD}.ldap_group_members", new_callable=AsyncMock
    ) as mock_client:
        mock_client.return_value = LdapGroupMembersResponse(
            groups=[
                LdapGroupResult(
                    group="team-a",
                    members=[LdapGroupMember(name="shared", org_username="shared")],
                )
            ]
        )
        permission_query.return_value.permissions = [_permission(roles=roles)]
        permissions = await integration.get_permissions(
            query_func=MagicMock(), ldap_settings=_ldap_settings()
        )
        result = integration.compile_users_from_roles(permissions[0].roles)

    assert result == ["shared"]


@pytest.mark.asyncio
@pytest.mark.parametrize("gov_slack_email_local_part", [None, "alice.gov"])
async def test_process_permission_keeps_canonical_usernames_for_ldap_members(
    integration: SlackUsergroupsIntegration,
    gov_slack_email_local_part: str | None,
    permission_query: MagicMock,
) -> None:
    """Gov overrides are deferred until request construction."""
    permission = _permission(
        roles=[
            _role(
                users=[_frag_user("charlie", gov_slack_email_local_part="charlie.gov")],
                member_sources=[_ldap_membership_source()],
            )
        ]
    )
    users = [
        _app_user(
            "alice", "alice-gh", gov_slack_email_local_part=gov_slack_email_local_part
        ),
        _app_user("charlie", "charlie-gh"),
        _app_user("unrelated", "unrelated-gh", gov_slack_email_local_part="other.gov"),
    ]
    with patch(
        f"{_LDAP_RESOLVER_MOD}.ldap_group_members", new_callable=AsyncMock
    ) as mock_client:
        mock_client.return_value = LdapGroupMembersResponse(
            groups=[
                LdapGroupResult(
                    group="team-a",
                    members=[
                        LdapGroupMember(name="alice", org_username="alice"),
                        LdapGroupMember(name="bob", org_username="bob"),
                    ],
                )
            ]
        )
        permission_query.return_value.permissions = [permission]
        permissions = await integration.get_permissions(
            query_func=MagicMock(), ldap_settings=_ldap_settings()
        )
        result = await integration._process_permission(
            permissions[0], users, [], _ldap_settings(), None, None
        )

    assert result is not None
    assert result[1].config.users == sorted([
        "alice",
        "bob",
        "charlie",
    ])


# --- compute_cluster_user_group + include_user_to_cluster_usergroup ---


def test_compute_cluster_user_group() -> None:
    assert (
        SlackUsergroupsIntegration.compute_cluster_user_group("app-sre-prod")
        == "app-sre-prod-cluster"
    )


def _cluster_role(tag: bool | None) -> ClusterAccessRole:
    return ClusterAccessRole(
        name="r",
        access=None,
        expirationDate=None,
        memberSources=None,
        users=[],
        tag_on_cluster_updates=tag,
    )


@pytest.mark.parametrize(
    ("user_tag", "role_tag", "expected"),
    [
        (True, False, True),  # user override wins
        (False, True, False),  # user override wins
        (None, True, True),  # fall back to role
        (None, False, False),  # role disables
        (None, None, True),  # default include
    ],
)
def test_include_user_to_cluster_usergroup(
    user_tag: bool | None, role_tag: bool | None, expected: bool
) -> None:
    user = _cluster_user("alice", tag_on_cluster_updates=user_tag)
    role = _cluster_role(role_tag)
    assert (
        SlackUsergroupsIntegration.include_user_to_cluster_usergroup(user, role)
        is expected
    )


# --- fetch_owners ---


@pytest.mark.asyncio
async def test_fetch_owners_github_maps_login(
    integration: SlackUsergroupsIntegration,
) -> None:
    users = [_app_user("alice", "AliceGH")]
    gh_to_org = {"alicegh": "alice"}
    users_map = {"alice": users[0]}
    with patch(f"{_MOD}.vcs_repo_owners", new_callable=AsyncMock) as mock_owners:
        mock_owners.return_value = RepoOwnersResponse(
            approvers=["alicegh"], reviewers=[], provider=VCSProvider.GITHUB
        )
        result = await integration.fetch_owners(
            "https://github.com/org/repo",
            _vault_secret(),
            gh_to_org,
            users_map,
        )
    assert result == ["alice"]
    # default ref is master
    assert mock_owners.call_args.kwargs["ref"] == "master"


@pytest.mark.asyncio
async def test_fetch_owners_parses_branch_ref(
    integration: SlackUsergroupsIntegration,
) -> None:
    with patch(f"{_MOD}.vcs_repo_owners", new_callable=AsyncMock) as mock_owners:
        mock_owners.return_value = RepoOwnersResponse(
            approvers=[], reviewers=[], provider=VCSProvider.GITHUB
        )
        await integration.fetch_owners(
            "https://github.com/org/repo:main",
            _vault_secret(),
            {},
            {},
        )
    assert mock_owners.call_args.kwargs["repo_url"] == "https://github.com/org/repo"
    assert mock_owners.call_args.kwargs["ref"] == "main"


@pytest.mark.asyncio
async def test_fetch_owners_gitlab_uses_org_username(
    integration: SlackUsergroupsIntegration,
) -> None:
    users = [_app_user("alice", "AliceGH")]
    users_map = {"alice": users[0]}
    with patch(f"{_MOD}.vcs_repo_owners", new_callable=AsyncMock) as mock_owners:
        mock_owners.return_value = RepoOwnersResponse(
            approvers=["alice"], reviewers=[], provider=VCSProvider.GITLAB
        )
        result = await integration.fetch_owners(
            "https://gitlab.example.com/org/repo",
            _vault_secret(),
            {},
            users_map,
        )
    assert result == ["alice"]


@pytest.mark.asyncio
async def test_fetch_owners_excludes_tag_on_merge_requests_false(
    integration: SlackUsergroupsIntegration,
) -> None:
    users = [_app_user("alice", "AliceGH", tag_on_merge_requests=False)]
    users_map = {"alice": users[0]}
    with patch(f"{_MOD}.vcs_repo_owners", new_callable=AsyncMock) as mock_owners:
        mock_owners.return_value = RepoOwnersResponse(
            approvers=["alice"], reviewers=[], provider=VCSProvider.GITLAB
        )
        result = await integration.fetch_owners(
            "https://gitlab.example.com/org/repo",
            _vault_secret(),
            {},
            users_map,
        )
    assert result == []


# --- compile_users_from_git_owners ---


@pytest.mark.asyncio
async def test_compile_users_from_git_owners_none(
    integration: SlackUsergroupsIntegration,
) -> None:
    result = await integration.compile_users_from_git_owners(
        urls=None, vcs_instances=[], app_interface_users=[]
    )
    assert result == []


@pytest.mark.asyncio
async def test_compile_users_from_git_owners_aggregates_unique(
    integration: SlackUsergroupsIntegration,
) -> None:
    users = [_app_user("alice", "AliceGH"), _app_user("bob", "BobGH")]
    with (
        patch(f"{_MOD}.get_token_from_url", return_value=_vault_secret()),
        patch(f"{_MOD}.vcs_repo_owners", new_callable=AsyncMock) as mock_owners,
    ):
        mock_owners.side_effect = [
            RepoOwnersResponse(
                approvers=["alicegh"], reviewers=["bobgh"], provider=VCSProvider.GITHUB
            ),
            RepoOwnersResponse(
                approvers=["alicegh"], reviewers=[], provider=VCSProvider.GITHUB
            ),
        ]
        result = await integration.compile_users_from_git_owners(
            urls=["https://github.com/o/r1", "https://github.com/o/r2"],
            vcs_instances=[],
            app_interface_users=users,
        )
    assert sorted(result) == ["alice", "bob"]


# --- compile_users_from_pagerduty_schedules ---


@pytest.mark.asyncio
async def test_compile_users_from_pagerduty_none(
    integration: SlackUsergroupsIntegration,
) -> None:
    result = await integration.compile_users_from_pagerduty_schedules(
        pagerduties=None, app_interface_users=[]
    )
    assert result == []


@pytest.mark.asyncio
async def test_compile_users_from_pagerduty_maps_usernames(
    integration: SlackUsergroupsIntegration,
) -> None:
    instance = PagerDutyInstanceV1(token=_vault_secret("secret/pd"))
    pagerduties = [
        PagerDutyTargetV1(
            name="sched",
            instance=instance,
            scheduleID="SCHED1",
            escalationPolicyID=None,
        ),
        PagerDutyTargetV1(
            name="policy",
            instance=instance,
            scheduleID=None,
            escalationPolicyID="POLICY1",
        ),
    ]
    users = [_app_user("alice", "AliceGH", pagerduty_username="alice-pd")]
    with (
        patch(f"{_MOD}.pagerduty_schedule_users", new_callable=AsyncMock) as mock_sched,
        patch(
            f"{_MOD}.pagerduty_escalation_policy_users", new_callable=AsyncMock
        ) as mock_policy,
    ):
        mock_sched.return_value = ScheduleUsersResponse(
            users=[PagerDutyUser(username="alice-pd")]
        )
        mock_policy.return_value = EscalationPolicyUsersResponse(
            users=[PagerDutyUser(username="carol")]
        )
        result = await integration.compile_users_from_pagerduty_schedules(
            pagerduties=pagerduties, app_interface_users=users
        )
    # alice-pd maps to org_username alice; carol has no mapping -> passthrough
    assert sorted(result) == ["alice", "carol"]


# --- GitHub org membership (APPSRE-15221) ---


@pytest.mark.asyncio
async def test_github_org_none_returns_empty(
    integration: SlackUsergroupsIntegration,
) -> None:
    with (
        patch(f"{_MOD}.github_org_members", new_callable=AsyncMock) as mock_members,
        patch(f"{_MOD}.ldap_github_usernames", new_callable=AsyncMock) as mock_ldap,
    ):
        result = await integration.compile_users_from_github_org(
            github_org=None,
            app_interface_users=[_app_user("alice", "alice-gh")],
            ldap_settings=_ldap_settings(),
        )
    assert result == []
    mock_members.assert_not_called()
    mock_ldap.assert_not_called()


@pytest.mark.asyncio
async def test_github_org_resolves_via_app_interface(
    integration: SlackUsergroupsIntegration,
) -> None:
    users = [
        _app_user("alice", "AliceGH"),
        _app_user("bob", "bob-gh", gov_slack_email_local_part="bob.gov"),
    ]
    with (
        patch(f"{_MOD}.github_org_members", new_callable=AsyncMock) as mock_members,
        patch(f"{_MOD}.ldap_github_usernames", new_callable=AsyncMock) as mock_ldap,
    ):
        mock_members.return_value = GithubOrgMembersResponse(
            members=["alicegh", "bob-gh"]
        )
        result = await integration.compile_users_from_github_org(
            github_org=_github_org(),
            app_interface_users=users,
            ldap_settings=_ldap_settings(),
        )
    assert result == ["alice", "bob"]
    mock_ldap.assert_not_called()


@pytest.mark.asyncio
async def test_github_org_falls_back_to_ldap(
    integration: SlackUsergroupsIntegration,
) -> None:
    users = [_app_user("alice", "AliceGH"), _app_user("carol", "carol-old")]
    with (
        patch(f"{_MOD}.github_org_members", new_callable=AsyncMock) as mock_members,
        patch(f"{_MOD}.ldap_github_usernames", new_callable=AsyncMock) as mock_ldap,
    ):
        mock_members.return_value = GithubOrgMembersResponse(
            members=["AliceGH", "carol-gh"]
        )
        mock_ldap.return_value = LdapGithubUsernamesResponse(
            users=[LdapGithubUser(github_username="carol-gh", org_username="carol")]
        )
        result = await integration.compile_users_from_github_org(
            github_org=_github_org(),
            app_interface_users=users,
            ldap_settings=_ldap_settings(),
        )
    assert result == ["alice", "carol"]
    mock_ldap.assert_called_once()
    request = mock_ldap.call_args.args[0]
    assert request.logins == ["carol-gh"]
    assert request.secret.server_url == "ldap://freeipa.example.com"
    assert request.secret.base_dn == "dc=example,dc=com"


@pytest.mark.asyncio
async def test_github_org_ldap_resolved_user_not_in_app_interface(
    integration: SlackUsergroupsIntegration,
) -> None:
    """A member resolvable only via LDAP (not an app-interface user) must still
    be added, using their org_username as the Slack identity."""
    users = [_app_user("alice", "AliceGH")]
    with (
        patch(f"{_MOD}.github_org_members", new_callable=AsyncMock) as mock_members,
        patch(f"{_MOD}.ldap_github_usernames", new_callable=AsyncMock) as mock_ldap,
    ):
        mock_members.return_value = GithubOrgMembersResponse(
            members=["AliceGH", "jiprocha"]
        )
        mock_ldap.return_value = LdapGithubUsernamesResponse(
            users=[LdapGithubUser(github_username="jiprocha", org_username="jiprocha")]
        )
        result = await integration.compile_users_from_github_org(
            github_org=_github_org(),
            app_interface_users=users,
            ldap_settings=_ldap_settings(),
        )
    assert result == ["alice", "jiprocha"]


@pytest.mark.asyncio
async def test_github_org_logs_and_skips_unresolved(
    integration: SlackUsergroupsIntegration,
    caplog: pytest.LogCaptureFixture,
) -> None:
    users = [_app_user("alice", "AliceGH")]
    with (
        patch(f"{_MOD}.github_org_members", new_callable=AsyncMock) as mock_members,
        patch(f"{_MOD}.ldap_github_usernames", new_callable=AsyncMock) as mock_ldap,
    ):
        mock_members.return_value = GithubOrgMembersResponse(
            members=["AliceGH", "ghost", "phantom"]
        )
        mock_ldap.return_value = LdapGithubUsernamesResponse(users=[])
        with caplog.at_level(logging.WARNING):
            result = await integration.compile_users_from_github_org(
                github_org=_github_org(),
                app_interface_users=users,
                ldap_settings=_ldap_settings(),
            )
    assert result == ["alice"]
    # Exactly ONE aggregated warning per org (keeps the #reconcile channel
    # quiet), but every unmapped GitHub username stays visible so the MR author
    # sees them in the app-interface MR check output, with the Rover fix hint.
    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "could not map" in r.message
    ]
    assert len(warnings) == 1
    message = warnings[0].message
    assert "ghost" in message
    assert "phantom" in message
    assert "https://github.com/ghost" in message
    assert "https://github.com/phantom" in message
    assert "Rover" in message


@pytest.mark.asyncio
async def test_github_org_no_members_skips_ldap(
    integration: SlackUsergroupsIntegration,
) -> None:
    with (
        patch(f"{_MOD}.github_org_members", new_callable=AsyncMock) as mock_members,
        patch(f"{_MOD}.ldap_github_usernames", new_callable=AsyncMock) as mock_ldap,
    ):
        mock_members.return_value = GithubOrgMembersResponse(members=[])
        result = await integration.compile_users_from_github_org(
            github_org=_github_org(),
            app_interface_users=[_app_user("alice", "AliceGH")],
            ldap_settings=_ldap_settings(),
        )
    assert result == []
    mock_ldap.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_github_logins_via_ldap_empty_input(
    integration: SlackUsergroupsIntegration,
) -> None:
    with patch(f"{_MOD}.ldap_github_usernames", new_callable=AsyncMock) as mock_ldap:
        result = await integration._resolve_github_logins_via_ldap([], _ldap_settings())
    assert result == {}
    mock_ldap.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_github_logins_via_ldap_missing_credentials(
    integration: SlackUsergroupsIntegration,
) -> None:
    with pytest.raises(RuntimeError, match="LDAP credentials not found"):
        await integration._resolve_github_logins_via_ldap(
            ["carol-gh"], _ldap_settings(with_credentials=False)
        )


# --- _process_permission ---


@pytest.mark.asyncio
async def test_process_permission_skip(
    integration: SlackUsergroupsIntegration,
) -> None:
    result = await integration._process_permission(
        _resolved_permission(_permission(skip=True)),
        [],
        [],
        _ldap_settings(),
        None,
        None,
    )
    assert result is None


@pytest.mark.asyncio
async def test_process_permission_no_managed_usergroups(
    integration: SlackUsergroupsIntegration,
) -> None:
    permission = _permission(workspace=_workspace(managed=[]))
    result = await integration._process_permission(
        _resolved_permission(permission), [], [], _ldap_settings(), None, None
    )
    assert result is None


@pytest.mark.asyncio
async def test_process_permission_workspace_filter_mismatch(
    integration: SlackUsergroupsIntegration,
) -> None:
    result = await integration._process_permission(
        _resolved_permission(_permission()),
        [],
        [],
        _ldap_settings(),
        "other-workspace",
        None,
    )
    assert result is None


@pytest.mark.asyncio
async def test_process_permission_usergroup_filter_mismatch(
    integration: SlackUsergroupsIntegration,
) -> None:
    result = await integration._process_permission(
        _resolved_permission(_permission()),
        [],
        [],
        _ldap_settings(),
        None,
        "other-handle",
    )
    assert result is None


@pytest.mark.asyncio
async def test_process_permission_handle_not_managed_raises(
    integration: SlackUsergroupsIntegration,
) -> None:
    # handle differs from the workspace's managed_usergroups entry
    permission = _permission(
        handle="team-handle", workspace=_workspace(managed=["different-handle"])
    )
    with pytest.raises(KeyError, match="not in 'managedUsergroups'"):
        await integration._process_permission(
            _resolved_permission(permission), [], [], _ldap_settings(), None, None
        )


@pytest.mark.asyncio
async def test_process_permission_builds_usergroup_with_notifications(
    integration: SlackUsergroupsIntegration,
) -> None:
    permission = _permission(
        roles=[_role(users=[_frag_user("alice"), _frag_user("bob")])],
        channels=["#b", "#a", "#a"],
        notifications=[
            SlackUsergroupNotificationV1(action="addUser", message="welcome"),
            SlackUsergroupNotificationV1(action="removeUser", message="bye"),
        ],
    )
    result = await integration._process_permission(
        _resolved_permission(permission), [], [], _ldap_settings(), None, None
    )
    assert result is not None
    workspace_name, usergroup = result
    assert workspace_name == "coreos"
    assert usergroup.handle == "team-handle"
    assert usergroup.config.users == ["alice", "bob"]
    assert usergroup.config.channels == ["#a", "#b"]
    assert [n.action for n in usergroup.config.notifications] == [
        "add-user",
        "remove-user",
    ]


@pytest.mark.asyncio
async def test_process_permission_unknown_notification_raises(
    integration: SlackUsergroupsIntegration,
) -> None:
    permission = _permission(
        roles=[_role(users=[_frag_user("alice")])],
        notifications=[
            SlackUsergroupNotificationV1(action="bogus", message="x"),
        ],
    )
    with pytest.raises(ValueError, match="Unknown notification action"):
        await integration._process_permission(
            _resolved_permission(permission), [], [], _ldap_settings(), None, None
        )


# --- compile_desired_state_from_permissions ---


@pytest.mark.asyncio
async def test_compile_desired_state_from_permissions_builds_workspace(
    integration: SlackUsergroupsIntegration,
) -> None:
    permission = _permission(roles=[_role(users=[_frag_user("alice")])])
    workspaces = await integration.compile_desired_state_from_permissions(
        permissions=[_resolved_permission(permission)],
        app_interface_users=[],
        vcs_instances=[],
        ldap_settings=_ldap_settings(),
    )
    assert len(workspaces) == 1
    ws = workspaces[0]
    assert ws.name == "coreos"
    assert ws.default_channel == "#general"
    assert ws.token.path == "secret/slack/token"
    assert [ug.handle for ug in ws.usergroups] == ["team-handle"]


@pytest.mark.asyncio
async def test_compile_desired_state_skips_workspace_without_integration(
    integration: SlackUsergroupsIntegration,
    caplog: pytest.LogCaptureFixture,
) -> None:
    permission = _permission(
        roles=[_role(users=[_frag_user("alice")])],
        workspace=_workspace(managed=["team-handle"], with_integration=False),
    )
    workspaces = await integration.compile_desired_state_from_permissions(
        permissions=[_resolved_permission(permission)],
        app_interface_users=[],
        vcs_instances=[],
        ldap_settings=_ldap_settings(),
    )
    assert workspaces == []
    assert any("no slack-usergroups integration" in r.message for r in caplog.records)


# --- compile_desired_state_cluster_usergroups ---


def _slack_workspace(name: str = "coreos") -> SlackWorkspace:
    return SlackWorkspace(
        name=name,
        usergroups=[],
        managed_usergroups=[],
        default_channel="#general",
        token=_vault_secret("secret/slack/token"),
    )


def test_cluster_usergroups_from_cluster_group_access(
    integration: SlackUsergroupsIntegration,
) -> None:
    cluster = EnabledClusterV1(name="prod", auth=[], disable=None)
    role = ClusterAccessRole(
        name="r",
        access=[
            AccessV1(
                cluster=AccessClusterV1(auth=[], name="prod"),
                group="prod-admins",
                namespace=None,
            )
        ],
        expirationDate=None,
        users=[_cluster_user("alice")],
        tag_on_cluster_updates=None,
        memberSources=None,
    )
    workspaces = integration.compile_desired_state_cluster_usergroups(
        workspaces=[_slack_workspace()],
        clusters=[cluster],
        roles=[role],
    )
    ws = workspaces[0]
    assert [ug.handle for ug in ws.usergroups] == ["prod-cluster"]
    assert ws.usergroups[0].config.users == ["alice"]
    # default channel is appended and usergroup registered as managed
    assert ws.usergroups[0].config.channels == ["#general"]
    assert "prod-cluster" in ws.managed_usergroups


def test_cluster_usergroups_from_namespace_access(
    integration: SlackUsergroupsIntegration,
) -> None:
    cluster = EnabledClusterV1(name="prod", auth=[], disable=None)
    namespace = NamespaceV1(
        cluster=NamespaceV1_ClusterV1(name="prod", auth=[]),
        delete=None,
        managedRoles=True,
    )
    role = ClusterAccessRole(
        name="r",
        access=[AccessV1(cluster=None, group=None, namespace=namespace)],
        expirationDate=None,
        users=[_cluster_user("alice")],
        tag_on_cluster_updates=None,
        memberSources=None,
    )
    workspaces = integration.compile_desired_state_cluster_usergroups(
        workspaces=[_slack_workspace()],
        clusters=[cluster],
        roles=[role],
    )
    assert workspaces[0].usergroups[0].config.users == ["alice"]


def test_cluster_usergroups_no_users_skipped(
    integration: SlackUsergroupsIntegration,
) -> None:
    cluster = EnabledClusterV1(name="prod", auth=[], disable=None)
    workspaces = integration.compile_desired_state_cluster_usergroups(
        workspaces=[_slack_workspace()],
        clusters=[cluster],
        roles=[],
    )
    assert workspaces[0].usergroups == []


def test_cluster_usergroups_respects_usergroup_filter(
    integration: SlackUsergroupsIntegration,
) -> None:
    cluster = EnabledClusterV1(name="prod", auth=[], disable=None)
    role = ClusterAccessRole(
        name="r",
        access=[
            AccessV1(
                cluster=AccessClusterV1(auth=[], name="prod"),
                group="prod-admins",
                namespace=None,
            )
        ],
        expirationDate=None,
        users=[_cluster_user("alice")],
        tag_on_cluster_updates=None,
        memberSources=None,
    )
    workspaces = integration.compile_desired_state_cluster_usergroups(
        workspaces=[_slack_workspace()],
        clusters=[cluster],
        roles=[role],
        desired_usergroup_name="other-cluster",
    )
    assert workspaces[0].usergroups == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role_tag", "explicit_tag", "expected"),
    [
        (None, None, {"alice", "bob"}),
        (True, False, {"alice"}),
        (False, True, {"bob"}),
        (False, None, set()),
    ],
)
async def test_cluster_get_roles_preserves_tagging_and_canonical_usernames(
    integration: SlackUsergroupsIntegration,
    ldap_endpoint: AsyncMock,
    mocker: MockerFixture,
    role_tag: bool | None,
    explicit_tag: bool | None,
    expected: set[str],
) -> None:
    role = ClusterAccessRole(
        name="role",
        access=[
            AccessV1(
                cluster=AccessClusterV1(name="prod", auth=[]),
                group="admins",
                namespace=None,
            )
        ],
        expirationDate=None,
        memberSources=[_ldap_membership_source(group="source-team")],
        users=[_cluster_user("bob", tag_on_cluster_updates=explicit_tag)],
        tag_on_cluster_updates=role_tag,
    )
    ldap_endpoint.return_value.groups[0].members[0].github_username = None
    mocker.patch(f"{_MOD}.roles_query", return_value=MagicMock(roles=[role]))
    roles = await integration.get_roles(query_func=MagicMock(), cluster_names={"prod"})
    assert [user.org_username for user in roles[0].users] == ["bob", "alice"]
    assert [user.org_username for user in role.users] == ["bob"]
    resolver = mocker.patch(
        f"{_MOD}.resolve_role_members",
        side_effect=AssertionError("Compiler must not resolve memberships"),
    )
    workspaces = integration.compile_desired_state_cluster_usergroups(
        workspaces=[_slack_workspace()],
        clusters=[EnabledClusterV1(name="prod", auth=[], disable=None)],
        roles=roles,
        app_interface_users=[
            _app_user("alice", "alice-gh", gov_slack_email_local_part="alice.gov")
        ],
    )
    assert {
        user for group in workspaces[0].usergroups for user in group.config.users
    } == expected
    resolver.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_tag", "role_tag", "expected"),
    [
        (False, True, set()),
        (True, False, {"alice"}),
        (None, True, {"alice"}),
        (None, False, set()),
    ],
)
async def test_ldap_cluster_members_preserve_local_user_tagging_override(
    integration: SlackUsergroupsIntegration,
    ldap_endpoint: AsyncMock,
    mocker: MockerFixture,
    user_tag: bool | None,
    role_tag: bool,
    expected: set[str],
) -> None:
    role = ClusterAccessRole(
        name="role",
        expirationDate=None,
        users=[],
        tag_on_cluster_updates=role_tag,
        access=[
            AccessV1(
                cluster=AccessClusterV1(name="prod", auth=[]),
                group="admins",
                namespace=None,
            )
        ],
        memberSources=[_ldap_membership_source(group="source-team")],
    )
    mocker.patch(f"{_MOD}.roles_query", return_value=MagicMock(roles=[role]))
    roles = await integration.get_roles(query_func=MagicMock(), cluster_names={"prod"})
    workspaces = integration.compile_desired_state_cluster_usergroups(
        workspaces=[_slack_workspace()],
        clusters=[EnabledClusterV1(name="prod", auth=[], disable=None)],
        roles=roles,
        app_interface_users=[
            _app_user("alice", "alice-gh", tag_on_cluster_updates=user_tag)
        ],
    )
    assert {
        user for group in workspaces[0].usergroups for user in group.config.users
    } == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("source_path", ["permissions", "clusters"])
@pytest.mark.parametrize("dry_run", [True, False])
async def test_slack_unresolved_sources_abort_before_submission(
    integration: SlackUsergroupsIntegration,
    ldap_endpoint: AsyncMock,
    mocker: MockerFixture,
    source_path: str,
    dry_run: bool,
) -> None:
    permission = _permission(
        roles=[_role(member_sources=[_ldap_membership_source(group="source-team")])]
        if source_path == "permissions"
        else []
    )
    role = ClusterAccessRole(
        name="role",
        expirationDate=None,
        tag_on_cluster_updates=None,
        users=[],
        access=[
            AccessV1(
                cluster=AccessClusterV1(name="prod", auth=[]),
                group="admins",
                namespace=None,
            )
        ],
        memberSources=[_ldap_membership_source(group="source-team")]
        if source_path == "clusters"
        else None,
    )
    mocker.patch(
        f"{_MOD}.permissions_query", return_value=MagicMock(permissions=[permission])
    )
    mocker.patch(f"{_MOD}.roles_query", return_value=MagicMock(roles=[role]))
    mocker.patch.object(integration, "get_users", return_value=[])
    mocker.patch.object(
        integration,
        "get_clusters",
        return_value=[EnabledClusterV1(name="prod", auth=[], disable=None)],
    )
    mocker.patch(f"{_MOD}.get_vcs_instances", return_value=[])
    mocker.patch(f"{_MOD}.get_ldap_settings", return_value=_ldap_settings())
    submit = mocker.patch(f"{_MOD}.slack_usergroups", new_callable=AsyncMock)
    ldap_endpoint.return_value = LdapGroupMembersResponse(groups=[])
    with pytest.raises(RuntimeError, match="could not be resolved"):
        await integration.async_run(dry_run=dry_run)
    submit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("getter", ["permissions", "roles"])
async def test_slack_filters_unselected_sources_before_resolution(
    integration: SlackUsergroupsIntegration,
    ldap_endpoint: AsyncMock,
    mocker: MockerFixture,
    getter: str,
) -> None:
    ldap_endpoint.side_effect = AssertionError(
        "Unselected configuration must not query LDAP"
    )
    if getter == "permissions":
        integration.params.usergroup_name = "selected"
        permission = _permission(
            handle="unselected",
            roles=[_role(member_sources=[_ldap_membership_source()])],
        )
        mocker.patch(
            f"{_MOD}.permissions_query",
            return_value=MagicMock(permissions=[permission]),
        )
        assert await integration.get_permissions(query_func=MagicMock()) == []
    else:
        role = ClusterAccessRole(
            name="role",
            expirationDate=None,
            tag_on_cluster_updates=None,
            users=[],
            access=[
                AccessV1(
                    cluster=AccessClusterV1(name="unselected", auth=[]),
                    group="admins",
                    namespace=None,
                )
            ],
            memberSources=[_ldap_membership_source()],
        )
        mocker.patch(f"{_MOD}.roles_query", return_value=MagicMock(roles=[role]))
        assert (
            await integration.get_roles(
                query_func=MagicMock(), cluster_names={"selected"}
            )
            == []
        )
    ldap_endpoint.assert_not_awaited()


# --- reconcile ---


@pytest.mark.asyncio
async def test_reconcile_builds_request_and_returns_response(
    integration: SlackUsergroupsIntegration,
) -> None:
    usergroup = SlackUsergroup(
        handle="team-handle",
        config=SlackUsergroupConfig(users=["alice"], channels=["#general"]),
    )
    workspace = SlackWorkspace(
        name="coreos",
        usergroups=[usergroup],
        managed_usergroups=["team-handle"],
        default_channel="#general",
        token=_vault_secret("secret/slack/token"),
    )
    with patch(f"{_MOD}.slack_usergroups", new_callable=AsyncMock) as mock_recon:
        mock_recon.return_value = SlackUsergroupsTaskResponse(
            id="req-1", status_url="http://api/status/req-1"
        )
        response = await integration.reconcile(
            workspaces=[workspace], dry_run=True, app_interface_users=[]
        )
    assert response.id == "req-1"
    request = mock_recon.call_args.args[0]
    assert request.dry_run is True
    assert request.workspaces[0].name == "coreos"
    assert request.workspaces[0].token.path == "secret/slack/token"


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [True, False])
async def test_reconcile_translates_only_post_payload_usernames(
    integration: SlackUsergroupsIntegration, mocker: MockerFixture, dry_run: bool
) -> None:
    from qontract_api_client.schemas import NotificationAddUser, NotificationRemoveUser

    canonical_users = [
        "alice",
        "commercial",
        "ldap-only",
        "bot",
        "shared-a",
        "shared-b",
        "alice",
    ]
    group = SlackUsergroup(
        handle="team",
        config=SlackUsergroupConfig(
            users=canonical_users,
            description="Team",
            channels=["#team"],
            notifications=[
                NotificationAddUser(message="added"),
                NotificationRemoveUser(message="removed"),
            ],
        ),
    )
    workspace = _slack_workspace()
    workspace.usergroups = [group]
    workspace.managed_usergroups = ["team"]
    before = workspace.model_dump()
    submit = mocker.patch(
        f"{_MOD}.slack_usergroups",
        new_callable=AsyncMock,
        return_value=SlackUsergroupsTaskResponse(id="task", status_url="/tasks/task"),
    )
    await integration.reconcile(
        workspaces=[workspace],
        dry_run=dry_run,
        app_interface_users=[
            _app_user("alice", "alice-gh", gov_slack_email_local_part="alice.gov"),
            _app_user("commercial", "commercial-gh", gov_slack_email_local_part=""),
            _app_user("bot", "bot-gh", gov_slack_email_local_part="bot.gov"),
            _app_user("shared-a", "a-gh", gov_slack_email_local_part="shared.gov"),
            _app_user("shared-b", "b-gh", gov_slack_email_local_part="shared.gov"),
        ],
    )
    request = submit.call_args.args[0]
    assert request.dry_run is dry_run
    submitted_group = request.workspaces[0].usergroups[0]
    assert submitted_group.config.users == [
        "alice.gov",
        "bot.gov",
        "commercial",
        "ldap-only",
        "shared.gov",
    ]
    assert submitted_group.handle == group.handle
    assert submitted_group.config.description == group.config.description
    assert submitted_group.config.channels == group.config.channels
    assert submitted_group.config.notifications == group.config.notifications
    assert request.workspaces[0].managed_usergroups == workspace.managed_usergroups
    assert workspace.model_dump() == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("gov_slack_username", "expected"),
    [("alice.gov", "alice.gov"), (None, "alice"), ("", "alice")],
)
async def test_reconcile_applies_gov_slack_override_at_post_boundary(
    integration: SlackUsergroupsIntegration,
    mocker: MockerFixture,
    gov_slack_username: str | None,
    expected: str,
) -> None:
    workspace = _slack_workspace()
    workspace.usergroups = [
        SlackUsergroup(handle="team", config=SlackUsergroupConfig(users=["alice"]))
    ]
    submit = mocker.patch(
        f"{_MOD}.slack_usergroups",
        new_callable=AsyncMock,
        return_value=SlackUsergroupsTaskResponse(id="task", status_url="/tasks/task"),
    )
    await integration.reconcile(
        workspaces=[workspace],
        dry_run=True,
        app_interface_users=[
            _app_user(
                "alice", "alice-gh", gov_slack_email_local_part=gov_slack_username
            )
        ],
    )
    assert submit.call_args.args[0].workspaces[0].usergroups[0].config.users == [
        expected
    ]
    assert workspace.usergroups[0].config.users == ["alice"]


@pytest.mark.asyncio
async def test_pagerduty_uses_canonical_username_until_gov_slack_post_translation(
    integration: SlackUsergroupsIntegration, mocker: MockerFixture
) -> None:
    users = [
        _app_user(
            "alice",
            "alice-gh",
            pagerduty_username="alice-pd",
            gov_slack_email_local_part="alice.gov",
        )
    ]
    target = PagerDutyTargetV1(
        name="schedule",
        instance=PagerDutyInstanceV1(token=_vault_secret()),
        scheduleID="schedule",
        escalationPolicyID=None,
    )
    mocker.patch(
        f"{_MOD}.pagerduty_schedule_users",
        new_callable=AsyncMock,
        return_value=ScheduleUsersResponse(users=[PagerDutyUser(username="alice-pd")]),
    )
    canonical_users = await integration.compile_users_from_pagerduty_schedules(
        pagerduties=[target],
        app_interface_users=users,
    )
    assert canonical_users == ["alice"]
    workspace = _slack_workspace()
    workspace.usergroups = [
        SlackUsergroup(
            handle="team", config=SlackUsergroupConfig(users=canonical_users)
        )
    ]
    submit = mocker.patch(
        f"{_MOD}.slack_usergroups",
        new_callable=AsyncMock,
        return_value=SlackUsergroupsTaskResponse(id="task", status_url="/tasks/task"),
    )
    await integration.reconcile(
        workspaces=[workspace], dry_run=True, app_interface_users=users
    )
    assert submit.call_args.args[0].workspaces[0].usergroups[0].config.users == [
        "alice.gov"
    ]
    assert workspace.usergroups[0].config.users == ["alice"]


def test_schedule_collector_keeps_canonical_org_usernames(
    integration: SlackUsergroupsIntegration,
) -> None:
    schedule = ScheduleV1(
        schedule=[
            ScheduleEntryV1(
                start="2000-01-01 00:00",
                end="2100-01-01 00:00",
                users=[_frag_user("alice", gov_slack_email_local_part="alice.gov")],
            )
        ]
    )
    assert integration.compile_users_from_schedule(schedule) == ["alice"]


# --- async_run ---


def _patch_async_run_deps(
    integration: SlackUsergroupsIntegration,
    *,
    workspaces: list[SlackWorkspace],
) -> tuple:
    """Patch the gql-backed inputs and compilation steps of async_run."""
    return (
        patch(f"{_MOD}.gql"),
        patch.object(type(integration), "get_permissions", return_value=[]),
        patch.object(type(integration), "get_users", return_value=[]),
        patch.object(type(integration), "get_clusters", return_value=[]),
        patch.object(type(integration), "get_roles", return_value=[]),
        patch(f"{_MOD}.get_vcs_instances", return_value=[]),
        patch(f"{_MOD}.get_ldap_settings", return_value=_ldap_settings()),
        patch.object(
            integration,
            "compile_desired_state_from_permissions",
            new=AsyncMock(return_value=workspaces),
        ),
        patch.object(
            integration,
            "compile_desired_state_cluster_usergroups",
            return_value=workspaces,
        ),
    )


@pytest.mark.asyncio
async def test_async_run_no_workspaces_returns_early(
    integration: SlackUsergroupsIntegration,
    caplog: pytest.LogCaptureFixture,
) -> None:
    patches = _patch_async_run_deps(integration, workspaces=[])
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        patches[8],
        patch.object(integration, "reconcile", new=AsyncMock()) as mock_recon,
        caplog.at_level(logging.DEBUG),
    ):
        await integration.async_run(dry_run=True)
    mock_recon.assert_not_called()
    assert any("No desired state found" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_async_run_apply_does_not_poll(
    integration: SlackUsergroupsIntegration,
) -> None:
    workspaces = [_slack_workspace()]
    patches = _patch_async_run_deps(integration, workspaces=workspaces)
    task_response = SlackUsergroupsTaskResponse(id="r", status_url="http://api/s")
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        patches[8],
        patch.object(
            integration, "reconcile", new=AsyncMock(return_value=task_response)
        ) as mock_recon,
        patch.object(integration, "poll_task_status", new=AsyncMock()) as mock_poll,
    ):
        await integration.async_run(dry_run=False)
    mock_recon.assert_awaited_once()
    assert mock_recon.call_args.kwargs["dry_run"] is False
    mock_poll.assert_not_called()


@pytest.mark.asyncio
async def test_async_run_dry_run_polls_and_logs_actions(
    integration: SlackUsergroupsIntegration,
    caplog: pytest.LogCaptureFixture,
) -> None:
    workspaces = [_slack_workspace()]
    patches = _patch_async_run_deps(integration, workspaces=workspaces)
    task_response = SlackUsergroupsTaskResponse(id="r", status_url="http://api/s")
    task_result = SlackUsergroupsTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[
            SlackUsergroupActionCreate(
                description="d", usergroup="ug", users=["alice"], workspace="coreos"
            ),
            SlackUsergroupActionUpdateUsers(
                usergroup="ug",
                users=["alice"],
                users_to_add=["alice"],
                users_to_remove=[],
                workspace="coreos",
            ),
            SlackUsergroupActionUpdateMetadata(
                channels=["#general"],
                description="d",
                usergroup="ug",
                workspace="coreos",
            ),
        ],
    )
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        patches[8],
        patch.object(
            integration, "reconcile", new=AsyncMock(return_value=task_response)
        ),
        patch.object(
            integration, "poll_task_status", new=AsyncMock(return_value=task_result)
        ) as mock_poll,
    ):
        await integration.async_run(dry_run=True)
    mock_poll.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_run_pending_task_exits(
    integration: SlackUsergroupsIntegration,
) -> None:
    workspaces = [_slack_workspace()]
    patches = _patch_async_run_deps(integration, workspaces=workspaces)
    task_response = SlackUsergroupsTaskResponse(id="r", status_url="http://api/s")
    task_result = SlackUsergroupsTaskResult(status=TaskStatus.PENDING, actions=[])
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        patches[8],
        patch.object(
            integration, "reconcile", new=AsyncMock(return_value=task_response)
        ),
        patch.object(
            integration, "poll_task_status", new=AsyncMock(return_value=task_result)
        ),
        pytest.raises(SystemExit),
    ):
        await integration.async_run(dry_run=True)


@pytest.mark.asyncio
async def test_async_run_errors_exit(
    integration: SlackUsergroupsIntegration,
) -> None:
    workspaces = [_slack_workspace()]
    patches = _patch_async_run_deps(integration, workspaces=workspaces)
    task_response = SlackUsergroupsTaskResponse(id="r", status_url="http://api/s")
    task_result = SlackUsergroupsTaskResult(
        status=TaskStatus.SUCCESS, actions=[], errors=["boom"]
    )
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        patches[8],
        patch.object(
            integration, "reconcile", new=AsyncMock(return_value=task_response)
        ),
        patch.object(
            integration, "poll_task_status", new=AsyncMock(return_value=task_result)
        ),
        pytest.raises(SystemExit),
    ):
        await integration.async_run(dry_run=True)
