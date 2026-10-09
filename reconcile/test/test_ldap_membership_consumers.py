"""Regression coverage for LDAP membership-source integration opt-ins."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel
from qontract_api_client.schemas import (
    GithubOwnersTaskResponse,
    GithubOwnersTaskResult,
    LdapGroupMember,
    LdapGroupMembersResponse,
    LdapGroupResult,
    TaskStatus,
)

from reconcile import (
    acs_rbac,
    github_org,
    gitlab_members,
    ocm_groups,
    ocm_groups_api,
    openshift_groups,
)
from reconcile.change_owners.approver import Approver
from reconcile.change_owners.self_service_roles import (
    change_type_contexts_for_self_service_roles,
)
from reconcile.github_owners_api import (
    GithubOwnersIntegration,
    GithubOwnersIntegrationParams,
)
from reconcile.gql_definitions.acs.acs_rbac import AcsRbacQueryData
from reconcile.gql_definitions.acs.acs_rbac import RoleV1 as AcsRole
from reconcile.gql_definitions.change_owners.queries.self_service_roles import (
    DatafileObjectV1,
)
from reconcile.gql_definitions.common.github_orgs import GithubOrgV1
from reconcile.gql_definitions.github_owners_api.roles import RoleV1 as GithubOwnersRole
from reconcile.gql_definitions.gitlab_members.permissions import (
    PermissionGitlabGroupMembershipV1,
)
from reconcile.gql_definitions.gitlab_members.permissions import (
    RoleV1 as GitlabRole,
)
from reconcile.gql_definitions.ocm_groups_api.roles import (
    OcmGroupsApiRolesQueryData,
)
from reconcile.gql_definitions.ocm_groups_api.roles import (
    RoleV1 as OcmRole,
)
from reconcile.gql_definitions.openshift_groups.managed_roles import (
    OpenshiftGroupsManagedRolesQueryData,
)
from reconcile.gql_definitions.openshift_groups.managed_roles import (
    RoleV1 as OpenshiftRole,
)
from reconcile.test.change_owners.fixtures import build_change_type, build_test_datafile
from reconcile.test.change_owners.fixtures import build_role as build_self_service_role
from reconcile.test.utils.membershipsources.fixtures import MockGithubUser as GithubUser
from reconcile.test.utils.membershipsources.fixtures import build_ldap_membership_source
from reconcile.utils.aggregated_list import AggregatedList
from reconcile.utils.runtime.desired_state_diff import build_desired_state_diff

if TYPE_CHECKING:
    from collections.abc import Callable
    from unittest.mock import AsyncMock

    from pytest_mock import MockerFixture


def _source_data() -> list[dict]:
    return [
        build_ldap_membership_source(name="ldap", group="source-team").model_dump(
            by_alias=True
        )
    ]


def test_gitlab_members_resolves_source_members(
    ldap_endpoint: AsyncMock, gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    role = gql_class_factory(
        GitlabRole,
        {"name": "role", "users": [], "bots": []},
    )
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    permission = gql_class_factory(
        PermissionGitlabGroupMembershipV1,
        {
            "name": "gitlab",
            "group": "team",
            "access": "maintainer",
            "roles": [],
        },
    )
    permission.roles = [role]
    permissions = gitlab_members.get_permissions(
        query_func=mocker.Mock(
            return_value={"permissions": [permission.model_dump(by_alias=True)]}
        )
    )
    desired = gitlab_members.build_desired_state_spec(
        "team", permissions, mocker.Mock(), []
    )
    assert desired.members["alice"].access_level == 40


def test_acs_rbac_includes_ldap_only_role(
    ldap_endpoint: AsyncMock, gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    role = gql_class_factory(
        AcsRole,
        {
            "name": "role",
            "users": [],
            "oidc_permissions": [
                {
                    "name": "analyst",
                    "description": "Analyst",
                    "service": "acs",
                    "instance": {"name": "acs"},
                    "permission_set": "analyst",
                    "clusters": [],
                    "namespaces": [],
                }
            ],
        },
    )
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    mocker.patch(
        "reconcile.acs_rbac.acs_rbac_query",
        return_value=AcsRbacQueryData(acs_rbacs=[role]),
    )
    desired = acs_rbac.AcsRbacIntegration().get_desired_state(mocker.Mock(), "acs")
    assert [assignment.value for assignment in desired[0].assignments] == ["alice"]


def test_openshift_groups_resolves_oidc_members(
    ldap_endpoint: AsyncMock, gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    role = gql_class_factory(
        OpenshiftRole,
        {
            "name": "role",
            "users": [],
            "access": [
                {
                    "cluster": {"name": "cluster", "auth": [{"service": "oidc"}]},
                    "group": "dedicated-admins",
                }
            ],
        },
    )
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    mocker.patch(
        "reconcile.openshift_groups.query_managed_roles",
        return_value=OpenshiftGroupsManagedRolesQueryData(roles=[role]),
    )
    assert openshift_groups.fetch_desired_state(["cluster"]) == [
        {"cluster": "cluster", "group": "dedicated-admins", "user": "alice"}
    ]


@pytest.mark.asyncio
async def test_ocm_groups_api_resolves_oidc_members(
    ldap_endpoint: AsyncMock, gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    role = gql_class_factory(
        OcmRole,
        {
            "name": "role",
            "users": [],
            "access": [
                {
                    "cluster": {"name": "cluster", "auth": [{"service": "oidc"}]},
                    "group": "dedicated-admins",
                }
            ],
        },
    )
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    mocker.patch(
        "reconcile.ocm_groups_api.roles_query",
        return_value=OcmGroupsApiRolesQueryData(roles=[role]),
    )
    desired = await ocm_groups_api._fetch_desired_state(["cluster"])
    assert [member.user for member in desired] == ["alice"]


def test_github_org_resolves_source_members(
    ldap_endpoint: AsyncMock, mocker: MockerFixture
) -> None:
    mocker.patch("reconcile.github_org.gql.get_api").return_value.query.return_value = {
        "roles": [
            {
                "name": "role",
                "users": [],
                "bots": [],
                "memberSources": _source_data(),
                "expirationDate": None,
                "permissions": [
                    {"service": "github-org-team", "org": "org", "team": "team"}
                ],
            }
        ]
    }
    state = github_org.fetch_desired_state(infer_clusters=False).dump()
    assert all(group["items"] == ["alicegh"] for group in state)
    assert len(state) == 2


def test_change_owners_accepts_unaudited_ldap_source(
    ldap_endpoint: AsyncMock, mocker: MockerFixture
) -> None:
    role = build_self_service_role(
        name="role",
        change_type_name="change",
        datafiles=[DatafileObjectV1(datafileSchema="schema-1.yml", path="file.yml")],
        users=[],
    )
    role.member_sources = [
        build_ldap_membership_source(
            name="ldap", group="source-team", has_audit_trail=False
        )
    ]
    change_type = build_change_type(
        name="change", change_selectors=["allowed"], context_schema="schema-1.yml"
    )
    datafile = build_test_datafile(
        content={"allowed": "old"}, filepath="file.yml", schema="schema-1.yml"
    )
    change = datafile.create_bundle_change(jsonpath_patches={"allowed": "new"})
    comparison_query = mocker.Mock()
    comparison_query.return_value = {"roles": [role.model_dump(by_alias=True)]}
    from reconcile.change_owners.self_service_roles import fetch_self_service_roles

    contexts = change_type_contexts_for_self_service_roles(
        fetch_self_service_roles(mocker.Mock(query=comparison_query)),
        [change_type],
        [change],
    )
    assert len(contexts) == 1
    assert contexts[0][1].approvers == [Approver("alice", None)]
    ldap_endpoint.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("fail_resolution", [True, False])
async def test_github_owners_resolves_source_and_keeps_github_only_bot(
    ldap_endpoint: AsyncMock,
    gql_class_factory: Callable,
    mocker: MockerFixture,
    dry_run: bool,
    fail_resolution: bool,
    membership_case: MembershipCase,
) -> None:
    role = gql_class_factory(
        GithubOwnersRole,
        {
            "name": "role",
            "users": [user.model_dump() for user in membership_case.explicit_users],
            "bots": [{"github_username": "BotGH"}],
            "permissions": [
                {"service": "github-org-team", "org": "org", "role": "owner"}
            ],
        },
    )
    role.member_sources = (
        [build_ldap_membership_source(name="ldap", group="source-team")]
        if membership_case.use_source
        else None
    )
    org = gql_class_factory(
        GithubOrgV1, {"name": "org", "token": {"path": "github/token"}}
    )
    integration = GithubOwnersIntegration(GithubOwnersIntegrationParams())
    from reconcile.gql_definitions.github_owners_api.roles import (
        GithubOwnersApiRolesQueryData,
    )

    mocker.patch(
        "reconcile.github_owners_api.roles_query",
        return_value=GithubOwnersApiRolesQueryData(roles=[role]),
    )
    mocker.patch.object(integration, "get_github_orgs", return_value={"org": org})
    mocker.patch.object(
        GithubOwnersIntegration,
        "secret_manager_url",
        new_callable=mocker.PropertyMock,
        return_value="https://vault.example.com",
    )
    reconcile = mocker.patch(
        "reconcile.github_owners_api.reconcile_github_owners",
        new_callable=mocker.AsyncMock,
        return_value=GithubOwnersTaskResponse(
            id="task", status=TaskStatus.PENDING, status_url="/task"
        ),
    )
    mocker.patch.object(
        integration,
        "poll_task_status",
        new_callable=mocker.AsyncMock,
        return_value=GithubOwnersTaskResult(
            status=TaskStatus.SUCCESS, actions=[], errors=[]
        ),
    )
    if fail_resolution and membership_case.use_source:
        ldap_endpoint.return_value = LdapGroupMembersResponse(groups=[])
        with pytest.raises(RuntimeError, match="could not be resolved"):
            await integration.async_run(dry_run=dry_run)
        reconcile.assert_not_awaited()
    else:
        await integration.async_run(dry_run=dry_run)
        request = reconcile.call_args.args[0]
        assert request.dry_run is dry_run
        assert request.organizations[0].owners == sorted([
            *membership_case.expected_github,
            "botgh",
        ])


def test_gitlab_members_early_exit_keeps_membership_source_configuration(
    mocker: MockerFixture, gql_class_factory: Callable
) -> None:
    role = gql_class_factory(GitlabRole, {"name": "role", "users": [], "bots": []})
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    permission = gql_class_factory(PermissionGitlabGroupMembershipV1, {"roles": []})
    permission.roles = [role]
    mocker.patch("reconcile.gitlab_members.gql.get_api")
    mocker.patch(
        "reconcile.gitlab_members._query_permissions", return_value=[permission]
    )
    mocker.patch(
        "reconcile.gitlab_members.get_gitlab_instance"
    ).return_value.model_dump.return_value = {"name": "instance"}
    resolver = mocker.patch("reconcile.gitlab_members.resolve_role_members")
    before = gitlab_members.early_exit_desired_state()
    assert before == {
        "instance": {"name": "instance"},
        "permissions": [permission.model_dump()],
    }
    assert build_desired_state_diff(None, before, before).can_exit_early()
    role.member_sources[0].group = "another-team"
    after = gitlab_members.early_exit_desired_state()
    assert after is not None
    assert not build_desired_state_diff(None, before, after).can_exit_early()
    resolver.assert_not_called()


class MembershipCase(BaseModel, frozen=True):
    explicit_users: tuple[GithubUser, ...] = ()
    source_members: tuple[LdapGroupMember, ...] = ()
    use_source: bool = True
    expected_org: tuple[str, ...] = ()
    expected_github: tuple[str, ...] = ()


@pytest.fixture(
    params=[
        MembershipCase(
            explicit_users=(
                GithubUser(org_username="local", github_username="LocalGH"),
            ),
            use_source=False,
            expected_org=("local",),
            expected_github=("localgh",),
        ),
        MembershipCase(
            source_members=(
                LdapGroupMember(
                    name="alice", org_username="alice", github_username="AliceGH"
                ),
            ),
            expected_org=("alice",),
            expected_github=("alicegh",),
        ),
        MembershipCase(
            explicit_users=(
                GithubUser(org_username="alice", github_username="ExplicitGH"),
            ),
            source_members=(
                LdapGroupMember(
                    name="alice", org_username="alice", github_username="OtherGH"
                ),
                LdapGroupMember(
                    name="bob", org_username="bob", github_username="BobGH"
                ),
            ),
            expected_org=("alice", "bob"),
            expected_github=("explicitgh", "bobgh"),
        ),
        MembershipCase(),
        MembershipCase(
            source_members=(
                LdapGroupMember(
                    name="alice", org_username="alice", github_username=None
                ),
            ),
            expected_org=("alice",),
        ),
    ],
    ids=["explicit-only", "ldap-only", "hybrid", "empty", "missing-github"],
)
def membership_case(
    request: pytest.FixtureRequest, ldap_endpoint: AsyncMock
) -> MembershipCase:
    case = MembershipCase.model_validate(request.param)
    ldap_endpoint.return_value = LdapGroupMembersResponse(
        groups=[LdapGroupResult(group="source-team", members=list(case.source_members))]
    )
    if not case.use_source:
        ldap_endpoint.side_effect = AssertionError(
            "Explicit-only roles must not query LDAP"
        )
    return case


@pytest.mark.parametrize(
    "consumer",
    ["gitlab-members", "acs-rbac", "openshift-groups", "github-org"],
)
def test_membership_modes(
    consumer: str,
    membership_case: MembershipCase,
    gql_class_factory: Callable,
    mocker: MockerFixture,
) -> None:
    case = membership_case
    users = [user.model_dump() for user in case.explicit_users]
    sources = (
        [build_ldap_membership_source(name="ldap", group="source-team")]
        if case.use_source
        else None
    )
    match consumer:
        case "gitlab-members":
            role = gql_class_factory(
                GitlabRole,
                {
                    "name": "role",
                    "users": [
                        {"org_username": user.org_username}
                        for user in case.explicit_users
                    ],
                    "bots": [],
                },
            )
            role.member_sources = sources
            permission = gql_class_factory(
                PermissionGitlabGroupMembershipV1,
                {
                    "name": "gitlab",
                    "group": "team",
                    "access": "maintainer",
                    "roles": [],
                },
            )
            permission.roles = [role]
            permissions = gitlab_members.get_permissions(
                query_func=mocker.Mock(
                    return_value={"permissions": [permission.model_dump(by_alias=True)]}
                )
            )
            gitlab_desired = gitlab_members.build_desired_state_spec(
                "team", permissions, mocker.Mock(), []
            )
            assert tuple(gitlab_desired.members) == case.expected_org
        case "acs-rbac":
            role = gql_class_factory(
                AcsRole,
                {
                    "name": "role",
                    "users": [
                        {"org_username": user.org_username}
                        for user in case.explicit_users
                    ],
                    "oidc_permissions": [
                        {
                            "name": "analyst",
                            "description": "Analyst",
                            "service": "acs",
                            "instance": {"name": "acs"},
                            "permission_set": "analyst",
                            "clusters": [],
                            "namespaces": [],
                        }
                    ],
                },
            )
            role.member_sources = sources
            mocker.patch(
                "reconcile.acs_rbac.acs_rbac_query",
                return_value=AcsRbacQueryData(acs_rbacs=[role]),
            )
            acs_desired = acs_rbac.AcsRbacIntegration().get_desired_state(
                mocker.Mock(), "acs"
            )
            assert (
                tuple(assignment.value for assignment in acs_desired[0].assignments)
                == case.expected_org
            )
        case "openshift-groups":
            role = gql_class_factory(
                OpenshiftRole,
                {
                    "name": "role",
                    "users": users,
                    "access": [
                        {
                            "cluster": {
                                "name": "cluster",
                                "auth": [{"service": "oidc"}],
                            },
                            "group": "dedicated-admins",
                        }
                    ],
                },
            )
            role.member_sources = sources
            mocker.patch(
                "reconcile.openshift_groups.query_managed_roles",
                return_value=OpenshiftGroupsManagedRolesQueryData(roles=[role]),
            )
            openshift_desired = openshift_groups.fetch_desired_state(["cluster"])
            assert (
                tuple(member["user"] for member in openshift_desired)
                == case.expected_org
            )
        case "github-org":
            from reconcile.gql_definitions.github_org.roles import (
                GithubOrgRolesQueryData,
            )
            from reconcile.gql_definitions.github_org.roles import (
                RoleV1 as GithubRole,
            )

            role = gql_class_factory(
                GithubRole,
                {
                    "name": "role",
                    "users": users,
                    "bots": [],
                    "permissions": [
                        {"service": "github-org-team", "org": "org", "team": "team"}
                    ],
                },
            )
            role.member_sources = sources
            mocker.patch(
                "reconcile.github_org.roles_query",
                return_value=GithubOrgRolesQueryData(roles=[role]),
            )
            github_desired = github_org.fetch_desired_state(infer_clusters=False).dump()
            assert len(github_desired) == 2
            assert all(
                tuple(group["items"]) == case.expected_github
                for group in github_desired
            )
        case _:
            pytest.fail(f"Unknown consumer: {consumer}")


@pytest.mark.asyncio
async def test_ocm_membership_modes(
    membership_case: MembershipCase, gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    role = gql_class_factory(
        OcmRole,
        {
            "name": "role",
            "users": [user.model_dump() for user in membership_case.explicit_users],
            "access": [
                {
                    "cluster": {"name": "cluster", "auth": [{"service": "oidc"}]},
                    "group": "dedicated-admins",
                }
            ],
        },
    )
    role.member_sources = (
        [build_ldap_membership_source(name="ldap", group="source-team")]
        if membership_case.use_source
        else None
    )
    mocker.patch(
        "reconcile.ocm_groups_api.roles_query",
        return_value=OcmGroupsApiRolesQueryData(roles=[role]),
    )
    desired = await ocm_groups_api._fetch_desired_state(["cluster"])
    assert tuple(member.user for member in desired) == membership_case.expected_org


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("consumer", ["openshift-groups", "ocm-groups"])
def test_cluster_resolution_failure_cannot_remove_members(
    consumer: str,
    dry_run: bool,
    ldap_endpoint: AsyncMock,
    gql_class_factory: Callable,
    mocker: MockerFixture,
) -> None:
    ldap_endpoint.return_value = LdapGroupMembersResponse(groups=[])
    role = gql_class_factory(
        OpenshiftRole,
        {
            "name": "role",
            "users": [],
            "access": [
                {
                    "cluster": {"name": "cluster", "auth": [{"service": "oidc"}]},
                    "group": "dedicated-admins",
                }
            ],
        },
    )
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    mocker.patch(
        "reconcile.openshift_groups.query_managed_roles",
        return_value=OpenshiftGroupsManagedRolesQueryData(roles=[role]),
    )
    cluster_map = mocker.Mock()
    cluster_map.clusters.return_value = ["cluster"]
    current_state = [
        {"cluster": "cluster", "group": "dedicated-admins", "user": "existing"}
    ]
    if consumer == "openshift-groups":
        mocker.patch(
            "reconcile.openshift_groups.fetch_current_state",
            return_value=(cluster_map, current_state, [], []),
        )
        act = mocker.patch("reconcile.openshift_groups.act")
        with pytest.raises(RuntimeError, match="could not be resolved"):
            openshift_groups.run(dry_run=dry_run)
    else:
        mocker.patch(
            "reconcile.ocm_groups.queries.get_clusters",
            return_value=[{"name": "cluster", "ocm": {}}],
        )
        mocker.patch("reconcile.ocm_groups.integration_is_enabled", return_value=True)
        mocker.patch(
            "reconcile.ocm_groups.fetch_current_state",
            return_value=(cluster_map, current_state),
        )
        act = mocker.patch("reconcile.ocm_groups.act")
        with pytest.raises(RuntimeError, match="could not be resolved"):
            ocm_groups.run(dry_run=dry_run)
    act.assert_not_called()


@pytest.mark.parametrize("dry_run", [True, False])
def test_github_resolution_failure_cannot_remove_members(
    dry_run: bool,
    ldap_endpoint: AsyncMock,
    gql_class_factory: Callable,
    mocker: MockerFixture,
) -> None:
    from reconcile.gql_definitions.github_org.roles import (
        GithubOrgRolesQueryData,
    )
    from reconcile.gql_definitions.github_org.roles import (
        RoleV1 as GithubRole,
    )

    ldap_endpoint.return_value = LdapGroupMembersResponse(groups=[])
    role = gql_class_factory(
        GithubRole,
        {
            "name": "role",
            "users": [],
            "bots": [],
            "permissions": [
                {"service": "github-org-team", "org": "org", "team": "team"}
            ],
        },
    )
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    mocker.patch(
        "reconcile.github_org.roles_query",
        return_value=GithubOrgRolesQueryData(roles=[role]),
    )
    mocker.patch("reconcile.github_org.get_config", return_value={})
    mocker.patch("reconcile.github_org.GHApiStore")
    mocker.patch(
        "reconcile.github_org.fetch_current_state", return_value=AggregatedList()
    )
    runner = mocker.patch("reconcile.github_org.RunnerAction")
    with pytest.raises(RuntimeError, match="could not be resolved"):
        github_org.run(dry_run=dry_run)
    runner.assert_not_called()


@pytest.mark.parametrize("dry_run", [True, False])
def test_acs_resolution_failure_cannot_remove_members(
    dry_run: bool,
    ldap_endpoint: AsyncMock,
    gql_class_factory: Callable,
    mocker: MockerFixture,
) -> None:
    ldap_endpoint.return_value = LdapGroupMembersResponse(groups=[])
    role = gql_class_factory(
        AcsRole,
        {
            "name": "role",
            "users": [],
            "oidc_permissions": [
                {
                    "name": "analyst",
                    "description": "Analyst",
                    "service": "acs",
                    "instance": {"name": "acs"},
                    "permission_set": "analyst",
                    "clusters": [],
                    "namespaces": [],
                }
            ],
        },
    )
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    mocker.patch(
        "reconcile.acs_rbac.acs_rbac_query",
        return_value=AcsRbacQueryData(acs_rbacs=[role]),
    )
    instance = mocker.Mock()
    instance.name = "acs"
    mocker.patch(
        "reconcile.acs_rbac.AcsRbacApi.get_acs_instances", return_value=[instance]
    )
    integration = acs_rbac.AcsRbacIntegration()
    reconcile = mocker.patch.object(integration, "reconcile")
    with pytest.raises(ExceptionGroup, match="ACS RBAC reconciliation errors") as error:
        integration.run(dry_run=dry_run)
    assert "could not be resolved" in str(error.value.exceptions[0])
    reconcile.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [True, False])
async def test_ocm_api_resolution_failure_does_not_submit_desired_state(
    dry_run: bool,
    ldap_endpoint: AsyncMock,
    gql_class_factory: Callable,
    mocker: MockerFixture,
) -> None:
    from reconcile.test.test_ocm_groups_api import make_cluster

    ldap_endpoint.return_value = LdapGroupMembersResponse(groups=[])
    role = gql_class_factory(
        OcmRole,
        {
            "name": "role",
            "users": [],
            "access": [
                {
                    "cluster": {"name": "cluster", "auth": [{"service": "oidc"}]},
                    "group": "dedicated-admins",
                }
            ],
        },
    )
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    mocker.patch(
        "reconcile.ocm_groups_api.roles_query",
        return_value=OcmGroupsApiRolesQueryData(roles=[role]),
    )
    mocker.patch(
        "reconcile.ocm_groups_api._get_clusters",
        return_value=[make_cluster(name="cluster")],
    )
    mocker.patch("reconcile.ocm_groups_api.integration_is_enabled", return_value=True)
    reconcile = mocker.patch(
        "reconcile.ocm_groups_api.reconcile_ocm_groups", new_callable=mocker.AsyncMock
    )
    integration = ocm_groups_api.OcmGroupsIntegration(
        ocm_groups_api.OcmGroupsIntegrationParams()
    )
    with pytest.raises(RuntimeError, match="could not be resolved"):
        await integration.async_run(dry_run=dry_run)
    reconcile.assert_not_awaited()


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("consumer", ["openshift-groups", "ocm-groups"])
def test_cluster_source_members_are_reconciled(
    consumer: str,
    dry_run: bool,
    ldap_endpoint: AsyncMock,
    gql_class_factory: Callable,
    mocker: MockerFixture,
) -> None:
    role = gql_class_factory(
        OpenshiftRole,
        {
            "name": "role",
            "users": [],
            "access": [
                {
                    "cluster": {"name": "cluster", "auth": [{"service": "oidc"}]},
                    "group": "dedicated-admins",
                }
            ],
        },
    )
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    mocker.patch(
        "reconcile.openshift_groups.query_managed_roles",
        return_value=OpenshiftGroupsManagedRolesQueryData(roles=[role]),
    )
    mocker.patch("reconcile.openshift_groups.validate_diffs")
    mocker.patch(
        "reconcile.openshift_groups.ob.publish_cluster_desired_metrics_from_state"
    )
    cluster_map = mocker.Mock()
    cluster_map.clusters.return_value = ["cluster"]
    current_state = [
        {"cluster": "cluster", "group": "dedicated-admins", "user": "existing"}
    ]
    if consumer == "openshift-groups":
        mocker.patch(
            "reconcile.openshift_groups.fetch_current_state",
            return_value=(cluster_map, current_state, [], []),
        )
        act = mocker.patch("reconcile.openshift_groups.act")
        openshift_groups.run(dry_run=dry_run)
    else:
        mocker.patch(
            "reconcile.ocm_groups.queries.get_clusters",
            return_value=[{"name": "cluster", "ocm": {}}],
        )
        mocker.patch("reconcile.ocm_groups.integration_is_enabled", return_value=True)
        mocker.patch(
            "reconcile.ocm_groups.fetch_current_state",
            return_value=(cluster_map, current_state),
        )
        act = mocker.patch("reconcile.ocm_groups.act")
        ocm_groups.run(dry_run=dry_run)
    if dry_run:
        act.assert_not_called()
    else:
        assert {
            (call.args[0]["action"], call.args[0]["user"])
            for call in act.call_args_list
        } == {("add_user_to_group", "alice"), ("del_user_from_group", "existing")}


def test_change_owners_uses_comparison_bundle_for_resolution(
    ldap_endpoint: AsyncMock, mocker: MockerFixture
) -> None:
    from reconcile.change_owners.change_owners import cover_changes
    from reconcile.utils.membershipsources import async_resolver as role_members

    role = build_self_service_role(
        name="role", change_type_name="change", datafiles=[], users=[]
    )
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    comparison_api = mocker.Mock()
    comparison_api.query.return_value = {"roles": [role.model_dump(by_alias=True)]}
    mocker.patch(
        "reconcile.change_owners.change_owners.cover_changes_with_implicit_ownership"
    )
    lookup = mocker.spy(role_members, "get_ldap_settings")
    cover_changes([], [], comparison_api)
    lookup.assert_called_once_with(query_func=comparison_api.query)
    ldap_endpoint.assert_awaited_once()


def test_acs_explicit_empty_roles_preserve_previous_desired_state(
    gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    role = gql_class_factory(
        AcsRole,
        {
            "name": "role",
            "users": [],
            "oidc_permissions": [
                {
                    "name": "analyst",
                    "description": "Analyst",
                    "service": "acs",
                    "instance": {"name": "acs"},
                    "permission_set": "analyst",
                    "clusters": [],
                    "namespaces": [],
                }
            ],
        },
    )
    mocker.patch(
        "reconcile.acs_rbac.acs_rbac_query",
        return_value=AcsRbacQueryData(acs_rbacs=[role]),
    )
    assert acs_rbac.AcsRbacIntegration().get_desired_state(mocker.Mock(), "acs") == []


def test_missing_github_username_is_skipped_silently(
    ldap_endpoint: AsyncMock,
    gql_class_factory: Callable,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from reconcile.gql_definitions.github_org.roles import GithubOrgRolesQueryData
    from reconcile.gql_definitions.github_org.roles import RoleV1 as GithubRole

    ldap_endpoint.return_value = LdapGroupMembersResponse(
        groups=[
            LdapGroupResult(
                group="source-team",
                members=[
                    LdapGroupMember(
                        name="alice", org_username="alice", github_username=None
                    )
                ],
            )
        ]
    )
    role = gql_class_factory(
        GithubRole,
        {
            "name": "role",
            "users": [],
            "bots": [],
            "permissions": [
                {"service": "github-org-team", "org": "org", "team": "team"}
            ],
        },
    )
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    mocker.patch(
        "reconcile.github_org.roles_query",
        return_value=GithubOrgRolesQueryData(roles=[role]),
    )
    desired = github_org.fetch_desired_state(infer_clusters=False).dump()
    assert all(not group["items"] for group in desired)
    assert not caplog.records


@pytest.mark.parametrize("dry_run", [True, False])
def test_gitlab_resolution_failure_cannot_remove_members(
    dry_run: bool,
    ldap_endpoint: AsyncMock,
    gql_class_factory: Callable,
    mocker: MockerFixture,
) -> None:
    from reconcile.gql_definitions.gitlab_members.gitlab_instances import (
        GitlabInstanceV1,
    )

    ldap_endpoint.return_value = LdapGroupMembersResponse(groups=[])
    role = gql_class_factory(GitlabRole, {"name": "role", "users": [], "bots": []})
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    permission = gql_class_factory(
        PermissionGitlabGroupMembershipV1,
        {"name": "gitlab", "group": "team", "access": "maintainer", "roles": []},
    )
    permission.roles = [role]
    instance = gql_class_factory(
        GitlabInstanceV1, {"managedGroups": ["team"], "token": {"path": "gitlab/token"}}
    )
    mocker.patch(
        "reconcile.gitlab_members._query_permissions", return_value=[permission]
    )
    mocker.patch("reconcile.gitlab_members.get_gitlab_instance", return_value=instance)
    mocker.patch("reconcile.gitlab_members.users_query")
    mocker.patch("reconcile.gitlab_members.pagerduty_instances_query")
    mocker.patch("reconcile.gitlab_members.get_pagerduty_map")
    mocker.patch("reconcile.gitlab_members.queries.get_secret_reader_settings")
    mocker.patch("reconcile.gitlab_members.queries.get_app_interface_settings")
    mocker.patch("reconcile.gitlab_members.SecretReader")
    mocker.patch("reconcile.gitlab_members.GitLabApi")
    mocker.patch("reconcile.gitlab_members.get_managed_groups_map")
    mocker.patch("reconcile.gitlab_members.get_current_state")
    reconcile = mocker.patch("reconcile.gitlab_members.reconcile_gitlab_members")
    with pytest.raises(RuntimeError, match="could not be resolved"):
        gitlab_members.run(dry_run=dry_run)
    reconcile.assert_not_called()
