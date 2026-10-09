"""Membership-source regression coverage for the remaining access consumers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel
from qontract_api_client.schemas import (
    GlitchtipTaskResponse,
    GlitchtipTaskResult,
    LdapGroupMember,
    LdapGroupMembersResponse,
    LdapGroupResult,
    TaskStatus,
)

from reconcile import openshift_users, sendgrid_teammates
from reconcile.automated_actions.config.integration import (
    AutomatedActionsConfigIntegration,
    AutomatedActionsConfigIntegrationParams,
)
from reconcile.glitchtip_api.integration import (
    GlitchtipApiIntegration,
    GlitchtipApiIntegrationParams,
)
from reconcile.gql_definitions.automated_actions.instance import (
    AutomatedActionsInstanceV1,
    AutomatedActionV1,
    PermissionAutomatedActionsV1,
)
from reconcile.gql_definitions.automated_actions.instance import (
    RoleV1 as ActionRole,
)
from reconcile.gql_definitions.common.app_interface_clusterrole import (
    RoleV1 as ClusterRole,
)
from reconcile.gql_definitions.common.app_interface_roles import RoleV1
from reconcile.gql_definitions.common.app_interface_roles import UserV1 as BindingUser
from reconcile.gql_definitions.glitchtip.glitchtip_project import (
    GlitchtipProjectV1,
    ProjectsQueryData,
)
from reconcile.gql_definitions.ocm_aws_infrastructure_access.clusters import (
    ClusterSpecV1,
    OpenShiftClusterManagerV1,
)
from reconcile.gql_definitions.ocm_aws_infrastructure_access.clusters import (
    ClusterV1 as InfrastructureCluster,
)
from reconcile.gql_definitions.sendgrid_teammates.roles import RoleV1 as SendgridRole
from reconcile.openshift_bindings.openshift_clusterrolebindings import (
    OpenShiftClusterRoleBindingsIntegration,
    OpenShiftClusterRoleBindingsIntegrationParams,
)
from reconcile.openshift_bindings.openshift_rolebindings import (
    OpenShiftRoleBindingsIntegration,
    OpenShiftRoleBindingsIntegrationParams,
)
from reconcile.test.utils.membershipsources.fixtures import build_ldap_membership_source
from reconcile.utils.aws_iam_identity import MissingIamUsersError

if TYPE_CHECKING:
    from collections.abc import Callable
    from unittest.mock import AsyncMock

    from pytest_mock import MockerFixture


@pytest.fixture
def fetch_action_instances(
    gql_class_factory: Callable, mocker: MockerFixture
) -> Callable[[AutomatedActionV1], list[AutomatedActionsInstanceV1]]:
    def fetch(action: AutomatedActionV1) -> list[AutomatedActionsInstanceV1]:
        instance = gql_class_factory(
            AutomatedActionsInstanceV1, {"deployment": {"delete": False}}
        )
        instance.actions = [action]
        mocker.patch(
            "reconcile.automated_actions.config.integration.instance_query",
            return_value=mocker.Mock(automated_actions_instances_v1=[instance]),
        )
        integration = AutomatedActionsConfigIntegration(
            AutomatedActionsConfigIntegrationParams(thread_pool_size=1)
        )
        return list(
            integration.get_automated_actions_instances(query_func=mocker.Mock())
        )

    return fetch


@pytest.fixture
def fetch_infrastructure_clusters(
    gql_class_factory: Callable, mocker: MockerFixture
) -> Callable[[InfrastructureCluster], list[InfrastructureCluster]]:
    def fetch(cluster: InfrastructureCluster) -> list[InfrastructureCluster]:
        from reconcile import ocm_aws_infrastructure_access as module

        cluster.spec = ClusterSpecV1(product=module.OCM_PRODUCT_OSD)
        cluster.ocm = gql_class_factory(OpenShiftClusterManagerV1, {"name": "ocm"})
        mocker.patch.object(
            module, "clusters_query", return_value=mocker.Mock(clusters=[cluster])
        )
        return module.get_clusters()

    return fetch


@pytest.fixture
def namespace_role(gql_class_factory: Callable) -> RoleV1:
    role = gql_class_factory(
        RoleV1,
        {
            "name": "team",
            "users": [],
            "bots": [{"openshift_serviceaccount": "namespace/bot"}],
            "access": [
                {
                    "namespace": {
                        "name": "namespace",
                        "managedRoles": True,
                        "cluster": {"name": "cluster", "auth": [{"service": "oidc"}]},
                    },
                    "clusterRole": "view",
                }
            ],
        },
    )
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    return role


def test_rolebindings_include_ldap_users_and_keep_bots(
    ldap_endpoint: AsyncMock, namespace_role: RoleV1, mocker: MockerFixture
) -> None:
    mocker.patch(
        "reconcile.openshift_bindings.openshift_rolebindings.get_app_interface_roles",
        return_value=[namespace_role],
    )
    inventory = mocker.Mock()
    inventory.get_desired.return_value = None
    integration = OpenShiftRoleBindingsIntegration(
        OpenShiftRoleBindingsIntegrationParams()
    )
    integration.fetch_desired_state(inventory, allowed_clusters={"cluster"})
    assert {call.kwargs["name"] for call in inventory.add_desired.call_args_list} == {
        "view-alice",
        "view-namespace-bot",
    }


def test_clusterrolebindings_include_ldap_users(
    ldap_endpoint: AsyncMock, gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    role = gql_class_factory(
        ClusterRole,
        {
            "name": "team",
            "users": [],
            "access": [
                {
                    "cluster": {"name": "cluster", "auth": [{"service": "oidc"}]},
                    "clusterRole": "view",
                }
            ],
        },
    )
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    mocker.patch(
        "reconcile.openshift_bindings.openshift_clusterrolebindings.get_app_interface_clusterroles",
        return_value=[role],
    )
    inventory = mocker.Mock()
    inventory.get_desired.return_value = None
    integration = OpenShiftClusterRoleBindingsIntegration(
        OpenShiftClusterRoleBindingsIntegrationParams()
    )
    integration.fetch_desired_state(inventory, allowed_clusters={"cluster"})
    assert [call.kwargs["name"] for call in inventory.add_desired.call_args_list] == [
        "view-alice"
    ]


@pytest.mark.parametrize(
    ("allowed_clusters", "expected"),
    [(None, ["alice"]), ({"cluster"}, ["alice"]), ({"other"}, []), (set(), [])],
)
def test_openshift_user_cleanup_keeps_source_members(
    ldap_endpoint: AsyncMock,
    namespace_role: RoleV1,
    mocker: MockerFixture,
    allowed_clusters: set[str] | None,
    expected: list[str],
) -> None:
    mocker.patch(
        "reconcile.openshift_users.get_app_interface_roles",
        return_value=[namespace_role],
    )
    assert openshift_users.fetch_rolebindings_desired_state(
        allowed_clusters=allowed_clusters
    ) == [{"cluster": "cluster", "user": user} for user in expected]
    if not expected:
        ldap_endpoint.assert_not_awaited()


def test_openshift_cleanup_scopes_role_access_before_membership_resolution(
    ldap_endpoint: AsyncMock, namespace_role: RoleV1, mocker: MockerFixture
) -> None:
    assert namespace_role.access
    excluded = namespace_role.access[0].model_copy(deep=True)
    assert excluded.namespace
    excluded.namespace.cluster.name = "excluded"
    namespace_role.access.append(excluded)
    mocker.patch(
        "reconcile.openshift_users.get_app_interface_roles",
        return_value=[namespace_role],
    )
    resolver = mocker.spy(openshift_users, "resolve_role_members")

    assert openshift_users.fetch_rolebindings_desired_state(
        allowed_clusters={"cluster"}
    ) == [{"cluster": "cluster", "user": "alice"}]
    selected_role = resolver.call_args.args[0][0]
    assert [access.namespace.cluster.name for access in selected_role.access] == [
        "cluster"
    ]
    assert [
        access.namespace.cluster.name
        for access in namespace_role.access
        if access.namespace
    ] == ["cluster", "excluded"]
    assert selected_role is not namespace_role
    assert namespace_role.users == []


def test_openshift_user_cleanup_does_not_read_clusterrolebindings(
    mocker: MockerFixture,
) -> None:
    mocker.patch("reconcile.openshift_users.get_app_interface_roles", return_value=[])
    cluster_roles = mocker.patch(
        "reconcile.openshift_users.get_app_interface_clusterroles",
        create=True,
        side_effect=AssertionError(
            "ClusterRoleBinding cleanup is outside LDAP support"
        ),
    )
    mocker.patch(
        "reconcile.openshift_users.openshift_groups.fetch_desired_state",
        return_value=[],
    )
    oc_map = mocker.Mock()
    oc_map.clusters.return_value = ["cluster"]
    assert openshift_users.fetch_desired_state(oc_map) == []
    cluster_roles.assert_not_called()


def test_sendgrid_includes_ldap_only_role(
    ldap_endpoint: AsyncMock, gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    role = gql_class_factory(
        SendgridRole,
        {"name": "team", "users": [], "sendgrid_accounts": [{"name": "account"}]},
    )
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    desired = sendgrid_teammates.fetch_desired_state(
        sendgrid_teammates.get_roles(
            query_func=mocker.Mock(
                return_value={"roles": [role.model_dump(by_alias=True)]}
            )
        )
    )
    assert [user.email for user in desired["account"]] == ["alice@redhat.com"]


def test_automated_actions_authorizes_source_members(
    ldap_endpoint: AsyncMock,
    gql_class_factory: Callable,
    fetch_action_instances: Callable[
        [AutomatedActionV1], list[AutomatedActionsInstanceV1]
    ],
) -> None:
    role = gql_class_factory(ActionRole, {"name": "team", "users": [], "bots": []})
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    action = AutomatedActionV1(
        type="action",
        maxOps=1,
        permissions=[PermissionAutomatedActionsV1(roles=[role])],
    )
    integration = AutomatedActionsConfigIntegration(
        AutomatedActionsConfigIntegrationParams(thread_pool_size=1)
    )
    users = integration.compile_users(fetch_action_instances(action)[0].actions or [])
    assert [(user.username, user.roles) for user in users] == [("alice", {"team"})]


@pytest.mark.asyncio
async def test_glitchtip_includes_source_members(
    ldap_endpoint: AsyncMock, gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    project = gql_class_factory(
        GlitchtipProjectV1,
        {
            "name": "project",
            "platform": "python",
            "organization": {"name": "org", "instance": {"name": "instance"}},
            "teams": [
                {
                    "name": "team",
                    "roles": [
                        {
                            "name": "team-role",
                            "users": [],
                            "glitchtip_roles": [
                                {"organization": {"name": "org"}, "role": "admin"}
                            ],
                        }
                    ],
                }
            ],
        },
    )
    project.teams[0].roles[0].member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    integration = GlitchtipApiIntegration(GlitchtipApiIntegrationParams())
    query_func = mocker.Mock(
        return_value=ProjectsQueryData(glitchtip_projects=[project]).model_dump(
            by_alias=True
        )
    )
    projects = await integration.get_glitchtip_projects(query_func=query_func)
    assert type(projects[0]) is GlitchtipProjectV1
    assert projects[0].model_dump(exclude={"teams"}) == project.model_dump(
        exclude={"teams"}
    )
    desired = integration._build_desired_state(projects, mail_domain="redhat.com")
    assert [(user.email, user.role) for user in desired[0].users] == [
        ("alice@redhat.com", "admin")
    ]
    assert project.teams[0].roles[0].users == []


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("unresolved", [False, True])
async def test_glitchtip_resolves_selected_projects_before_submission(
    ldap_endpoint: AsyncMock,
    gql_class_factory: Callable,
    mocker: MockerFixture,
    dry_run: bool,
    unresolved: bool,
) -> None:
    from reconcile.glitchtip_api import integration as module
    from reconcile.gql_definitions.glitchtip.glitchtip_instance import (
        GlitchtipInstanceQueryData,
        GlitchtipInstanceV1,
    )

    selected = gql_class_factory(
        GlitchtipProjectV1,
        {
            "name": "project",
            "platform": "python",
            "organization": {"name": "org", "instance": {"name": "selected"}},
            "teams": [{"name": "team", "roles": [{"name": "role", "users": []}]}],
        },
    )
    selected.teams[0].roles[0].member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    unselected = gql_class_factory(
        GlitchtipProjectV1,
        {
            "name": "other",
            "platform": "python",
            "organization": {"name": "other", "instance": {"name": "unselected"}},
            "teams": [
                {"name": "other", "roles": [{"name": "other-role", "users": []}]}
            ],
        },
    )
    unselected.teams[0].roles[0].member_sources = [
        build_ldap_membership_source(name="ldap", group="must-not-resolve")
    ]
    instance = gql_class_factory(
        GlitchtipInstanceV1,
        {
            "name": "selected",
            "consoleUrl": "https://glitchtip.example.com",
            "mailDomain": "redhat.com",
            "automationToken": {"path": "token"},
            "automationUserEmail": {"path": "email"},
        },
    )
    mocker.patch.object(
        module,
        "glitchtip_instance_query",
        return_value=GlitchtipInstanceQueryData(instances=[instance]),
    )
    mocker.patch.object(
        module,
        "glitchtip_project_query",
        return_value=ProjectsQueryData(glitchtip_projects=[selected, unselected]),
    )
    query_func = mocker.Mock()
    mocker.patch.object(
        module.gql, "get_api", return_value=mocker.Mock(query=query_func)
    )
    mocker.patch.object(
        module.GlitchtipApiIntegration,
        "secret_manager_url",
        new_callable=mocker.PropertyMock,
        return_value="https://vault.example.com",
    )
    submit = mocker.patch.object(
        module,
        "reconcile_glitchtip",
        new_callable=mocker.AsyncMock,
        return_value=GlitchtipTaskResponse(id="task", status_url="/tasks/task"),
    )
    mocker.patch.object(
        module.GlitchtipApiIntegration,
        "poll_task_status",
        return_value=GlitchtipTaskResult(status=TaskStatus.SUCCESS),
    )
    resolver = mocker.spy(module, "resolve_role_members")
    integration = module.GlitchtipApiIntegration(
        module.GlitchtipApiIntegrationParams(instance="selected")
    )
    if unresolved:
        ldap_endpoint.return_value = LdapGroupMembersResponse(groups=[])
        with pytest.raises(RuntimeError, match="could not be resolved"):
            await integration.async_run(dry_run=dry_run)
        submit.assert_not_called()
    else:
        await integration.async_run(dry_run=dry_run)
        request = submit.call_args.args[0]
        assert request.dry_run is dry_run
        assert [user.email for user in request.instances[0].organizations[0].users] == [
            "alice@redhat.com"
        ]
    resolver.assert_awaited_once()
    assert [role.name for role in resolver.call_args.args[0]] == ["role"]
    assert resolver.call_args.kwargs["query_func"] is query_func
    assert selected.teams[0].roles[0].users == []


@pytest.mark.asyncio
async def test_glitchtip_overlapping_roles_keep_highest_access(
    ldap_endpoint: AsyncMock, gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    project = gql_class_factory(
        GlitchtipProjectV1,
        {
            "name": "project",
            "platform": "python",
            "organization": {"name": "org", "instance": {"name": "instance"}},
            "teams": [
                {
                    "name": "team",
                    "roles": [
                        {
                            "name": "admins",
                            "users": [],
                            "glitchtip_roles": [
                                {"organization": {"name": "org"}, "role": "admin"}
                            ],
                        },
                        {
                            "name": "members",
                            "users": [{"name": "Alice", "org_username": "alice"}],
                            "glitchtip_roles": [
                                {"organization": {"name": "org"}, "role": "member"}
                            ],
                        },
                    ],
                }
            ],
        },
    )
    project.teams[0].roles[0].member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    integration = GlitchtipApiIntegration(GlitchtipApiIntegrationParams())
    desired = integration._build_desired_state(
        await integration.get_glitchtip_projects(
            query_func=mocker.Mock(
                return_value=ProjectsQueryData(glitchtip_projects=[project]).model_dump(
                    by_alias=True
                )
            )
        ),
        mail_domain="redhat.com",
    )
    assert [(user.email, user.role) for user in desired[0].users] == [
        ("alice@redhat.com", "admin")
    ]


def test_infrastructure_access_resolves_ldap_members(
    ldap_endpoint: AsyncMock,
    gql_class_factory: Callable,
    mocker: MockerFixture,
    fetch_infrastructure_clusters: Callable[
        [InfrastructureCluster], list[InfrastructureCluster]
    ],
) -> None:
    from reconcile import ocm_aws_infrastructure_access as infrastructure

    cluster = gql_class_factory(
        InfrastructureCluster,
        {
            "name": "cluster",
            "awsInfrastructureAccess": [
                {
                    "accessLevel": "admin",
                    "awsGroup": {
                        "account": {
                            "name": "account",
                            "uid": "123",
                            "automationToken": {"path": "aws/token"},
                        },
                        "roles": [{"name": "team", "users": []}],
                    },
                }
            ],
        },
    )
    assert cluster.aws_infrastructure_access is not None
    cluster.aws_infrastructure_access[0].aws_group.roles[0].member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    mocker.patch(
        "reconcile.ocm_aws_infrastructure_access.get_namespaces", return_value=[]
    )
    mocker.patch(
        "reconcile.ocm_aws_infrastructure_access.queries.get_aws_accounts",
        return_value=[],
    )
    mocker.patch(
        "reconcile.ocm_aws_infrastructure_access.queries.get_app_interface_settings",
        return_value={},
    )
    aws = mocker.patch("reconcile.ocm_aws_infrastructure_access.AWSApi", create=True)
    aws.return_value.__enter__.return_value._get_account_users.return_value = ["alice"]
    desired = infrastructure.fetch_desired_state(fetch_infrastructure_clusters(cluster))
    assert [
        (grant.cluster, grant.user_arn, grant.access_level) for grant in desired
    ] == [("cluster", "arn:aws:iam::123:user/alice", "admin")]


def test_infrastructure_inventory_accepts_cluster_iterator(
    gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    from reconcile import ocm_aws_infrastructure_access as infrastructure

    cluster = gql_class_factory(InfrastructureCluster, {"name": "cluster"})
    mocker.patch(
        "reconcile.ocm_aws_infrastructure_access.queries.get_app_interface_settings",
        return_value={},
    )
    ocm = mocker.patch("reconcile.ocm_aws_infrastructure_access.OCMMap").return_value
    ocm.get.return_value.get_aws_infrastructure_access_role_grants.return_value = [
        ("arn:aws:iam::123:user/alice", "admin", "ready", "")
    ]
    _, current, failed, deleting = infrastructure.fetch_current_state(iter([cluster]))
    assert [grant.user_arn for grant in current] == ["arn:aws:iam::123:user/alice"]
    assert failed == deleting == []


class MemberMode(BaseModel, frozen=True):
    explicit: tuple[str, ...] = ()
    source: tuple[str, ...] = ()
    expected: tuple[str, ...] = ()
    use_sources: bool = True
    unresolved: bool = False


@pytest.fixture(
    params=[
        MemberMode(explicit=("local",), expected=("local",), use_sources=False),
        MemberMode(source=("alice",), expected=("alice",)),
        MemberMode(
            explicit=("alice",), source=("alice", "bob"), expected=("alice", "bob")
        ),
        MemberMode(),
        MemberMode(unresolved=True),
    ],
    ids=["explicit-only", "ldap-only", "hybrid", "empty", "unresolved"],
)
def member_mode(request: pytest.FixtureRequest, ldap_endpoint: AsyncMock) -> MemberMode:
    mode = MemberMode.model_validate(request.param)
    ldap_endpoint.return_value = LdapGroupMembersResponse(
        groups=[]
        if mode.unresolved
        else [
            LdapGroupResult(
                group="source-team",
                members=[
                    LdapGroupMember(name=uid, org_username=uid, github_username=None)
                    for uid in mode.source
                ],
            )
        ]
    )
    if not mode.use_sources:
        ldap_endpoint.side_effect = AssertionError(
            "Unexpected LDAP lookup for explicit-only role"
        )
    return mode


@pytest.mark.parametrize(
    "consumer",
    [
        "rolebindings",
        "clusterrolebindings",
        "openshift-users",
        "sendgrid",
        "automated-actions",
        "infrastructure",
    ],
)
def test_remaining_consumer_membership_modes(
    consumer: str,
    member_mode: MemberMode,
    namespace_role: RoleV1,
    gql_class_factory: Callable,
    mocker: MockerFixture,
    fetch_action_instances: Callable[
        [AutomatedActionV1], list[AutomatedActionsInstanceV1]
    ],
    fetch_infrastructure_clusters: Callable[
        [InfrastructureCluster], list[InfrastructureCluster]
    ],
) -> None:
    def consume() -> set[str]:
        sources = (
            [build_ldap_membership_source(name="ldap", group="source-team")]
            if member_mode.use_sources
            else None
        )
        users = [{"org_username": uid} for uid in member_mode.explicit]
        match consumer:
            case "rolebindings" | "openshift-users":
                namespace_role.users = [
                    BindingUser(org_username=uid, github_username=f"{uid}-github")
                    for uid in member_mode.explicit
                ]
                namespace_role.bots = []
                namespace_role.member_sources = sources
                if consumer == "openshift-users":
                    mocker.patch(
                        "reconcile.openshift_users.get_app_interface_roles",
                        return_value=[namespace_role],
                    )
                    return {
                        entry["user"]
                        for entry in openshift_users.fetch_rolebindings_desired_state(
                            allowed_clusters={"cluster"}
                        )
                    }
                mocker.patch(
                    "reconcile.openshift_bindings.openshift_rolebindings.get_app_interface_roles",
                    return_value=[namespace_role],
                )
                inventory = mocker.Mock()
                inventory.get_desired.return_value = None
                OpenShiftRoleBindingsIntegration(
                    OpenShiftRoleBindingsIntegrationParams()
                ).fetch_desired_state(inventory, allowed_clusters={"cluster"})
                return {
                    call.kwargs["value"].body["subjects"][0]["name"]
                    for call in inventory.add_desired.call_args_list
                }
            case "clusterrolebindings":
                role = gql_class_factory(
                    ClusterRole,
                    {
                        "name": "team",
                        "users": users,
                        "access": [
                            {
                                "cluster": {
                                    "name": "cluster",
                                    "auth": [{"service": "oidc"}],
                                },
                                "clusterRole": "view",
                            }
                        ],
                    },
                )
                role.member_sources = sources
                mocker.patch(
                    "reconcile.openshift_bindings.openshift_clusterrolebindings.get_app_interface_clusterroles",
                    return_value=[role],
                )
                inventory = mocker.Mock()
                inventory.get_desired.return_value = None
                OpenShiftClusterRoleBindingsIntegration(
                    OpenShiftClusterRoleBindingsIntegrationParams()
                ).fetch_desired_state(inventory, allowed_clusters={"cluster"})
                return {
                    call.kwargs["value"].body["subjects"][0]["name"]
                    for call in inventory.add_desired.call_args_list
                }
            case "sendgrid":
                role = gql_class_factory(
                    SendgridRole,
                    {
                        "name": "team",
                        "users": users,
                        "sendgrid_accounts": [{"name": "account"}],
                    },
                )
                role.member_sources = sources
                return {
                    user.email.split("@", 1)[0]
                    for user in sendgrid_teammates.fetch_desired_state(
                        sendgrid_teammates.get_roles(
                            query_func=mocker.Mock(
                                return_value={"roles": [role.model_dump(by_alias=True)]}
                            )
                        )
                    )["account"]
                }
            case "automated-actions":
                role = gql_class_factory(
                    ActionRole, {"name": "team", "users": users, "bots": []}
                )
                role.member_sources = sources
                action = AutomatedActionV1(
                    type="action",
                    maxOps=1,
                    permissions=[PermissionAutomatedActionsV1(roles=[role])],
                )
                return {
                    user.username
                    for user in AutomatedActionsConfigIntegration(
                        AutomatedActionsConfigIntegrationParams(thread_pool_size=1)
                    ).compile_users(fetch_action_instances(action)[0].actions or [])
                }
            case "infrastructure":
                from reconcile import ocm_aws_infrastructure_access as infrastructure

                cluster = gql_class_factory(
                    InfrastructureCluster,
                    {
                        "name": "cluster",
                        "awsInfrastructureAccess": [
                            {
                                "accessLevel": "admin",
                                "awsGroup": {
                                    "account": {
                                        "name": "account",
                                        "uid": "123",
                                        "automationToken": {"path": "aws/token"},
                                    },
                                    "roles": [{"name": "team", "users": users}],
                                },
                            }
                        ],
                    },
                )
                assert cluster.aws_infrastructure_access is not None
                cluster.aws_infrastructure_access[0].aws_group.roles[
                    0
                ].member_sources = sources
                mocker.patch(
                    "reconcile.ocm_aws_infrastructure_access.get_namespaces",
                    return_value=[],
                )
                mocker.patch(
                    "reconcile.ocm_aws_infrastructure_access.queries.get_aws_accounts",
                    return_value=[],
                )
                mocker.patch(
                    "reconcile.ocm_aws_infrastructure_access.queries.get_app_interface_settings",
                    return_value={},
                )
                aws = mocker.patch("reconcile.ocm_aws_infrastructure_access.AWSApi")
                aws.return_value.__enter__.return_value._get_account_users.return_value = list(
                    member_mode.expected
                )
                return {
                    grant.user_arn.rsplit("/", 1)[1]
                    for grant in infrastructure.fetch_desired_state(
                        fetch_infrastructure_clusters(cluster)
                    )
                }
            case _:
                pytest.fail(f"Unknown consumer {consumer}")

    if member_mode.unresolved:
        with pytest.raises(RuntimeError, match="could not be resolved"):
            consume()
    else:
        assert consume() == set(member_mode.expected)


@pytest.mark.asyncio
async def test_glitchtip_membership_modes(
    member_mode: MemberMode, gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    project = gql_class_factory(
        GlitchtipProjectV1,
        {
            "name": "project",
            "platform": "python",
            "organization": {"name": "org", "instance": {"name": "instance"}},
            "teams": [
                {
                    "name": "team",
                    "roles": [
                        {
                            "name": "role",
                            "users": [
                                {"name": uid, "org_username": uid}
                                for uid in member_mode.explicit
                            ],
                        }
                    ],
                }
            ],
        },
    )
    project.teams[0].roles[0].member_sources = (
        [build_ldap_membership_source(name="ldap", group="source-team")]
        if member_mode.use_sources
        else None
    )
    integration = GlitchtipApiIntegration(GlitchtipApiIntegrationParams())
    query_func = mocker.Mock(
        return_value=ProjectsQueryData(glitchtip_projects=[project]).model_dump(
            by_alias=True
        )
    )
    if member_mode.unresolved:
        with pytest.raises(RuntimeError, match="could not be resolved"):
            await integration.get_glitchtip_projects(query_func=query_func)
    else:
        desired = integration._build_desired_state(
            await integration.get_glitchtip_projects(query_func=query_func),
            mail_domain="redhat.com",
        )
        assert {user.email for user in desired[0].users} == {
            f"{uid}@redhat.com" for uid in member_mode.expected
        }


@pytest.mark.parametrize("dry_run", [True, False])
def test_missing_iam_user_cannot_revoke_infrastructure_grants(
    dry_run: bool,
    ldap_endpoint: AsyncMock,
    gql_class_factory: Callable,
    mocker: MockerFixture,
    fetch_infrastructure_clusters: Callable[
        [InfrastructureCluster], list[InfrastructureCluster]
    ],
) -> None:
    from reconcile import ocm_aws_infrastructure_access as infrastructure

    cluster = gql_class_factory(
        InfrastructureCluster,
        {
            "name": "cluster",
            "awsInfrastructureAccess": [
                {
                    "accessLevel": "admin",
                    "awsGroup": {
                        "account": {
                            "name": "account",
                            "uid": "123",
                            "automationToken": {"path": "aws/token"},
                        },
                        "roles": [{"name": "team", "users": []}],
                    },
                }
            ],
        },
    )
    assert cluster.aws_infrastructure_access is not None
    assert cluster.aws_infrastructure_access[0].aws_group.roles is not None
    cluster.aws_infrastructure_access[0].aws_group.roles[0].member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    mocker.patch(
        "reconcile.ocm_aws_infrastructure_access.get_clusters",
        return_value=fetch_infrastructure_clusters(cluster),
    )
    mocker.patch(
        "reconcile.ocm_aws_infrastructure_access.queries.get_app_interface_settings",
        return_value={},
    )
    aws = mocker.patch(
        "reconcile.ocm_aws_infrastructure_access.AWSApi"
    ).return_value.__enter__.return_value
    aws._get_account_users.return_value = []
    current = mocker.patch(
        "reconcile.ocm_aws_infrastructure_access.fetch_current_state"
    )
    apply = mocker.patch("reconcile.ocm_aws_infrastructure_access.act")
    with pytest.raises(MissingIamUsersError, match="alice"):
        infrastructure.run(dry_run=dry_run)
    current.assert_not_called()
    apply.assert_not_called()


def test_gitlab_permissions_resolve_members_at_fetch_boundary(
    ldap_endpoint: AsyncMock, gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    from reconcile import gitlab_members
    from reconcile.gql_definitions.gitlab_members.permissions import (
        PermissionGitlabGroupMembershipV1,
    )

    permission = gql_class_factory(
        PermissionGitlabGroupMembershipV1,
        {
            "group": "team",
            "access": "maintainer",
            "roles": [{"name": "role", "users": [], "bots": []}],
        },
    )
    assert permission.roles
    permission.roles[0].member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    query_func = mocker.Mock(
        return_value={"permissions": [permission.model_dump(by_alias=True)]}
    )
    fetched = gitlab_members.get_permissions(query_func=query_func)
    assert fetched[0].roles is not None
    assert [user.org_username for user in fetched[0].roles[0].users] == ["alice"]
    assert permission.roles is not None and permission.roles[0].users == []
    resolver = mocker.patch.object(
        gitlab_members,
        "resolve_role_members",
        side_effect=AssertionError("Builder must not resolve memberships"),
    )
    assert (
        gitlab_members
        .build_desired_state_spec("team", fetched, mocker.Mock(), [])
        .members["alice"]
        .access_level
        == 40
    )
    resolver.assert_not_called()


def test_self_service_roles_resolve_members_at_fetch_boundary(
    ldap_endpoint: AsyncMock, mocker: MockerFixture
) -> None:
    from reconcile.change_owners import self_service_roles
    from reconcile.test.change_owners.fixtures import build_role

    role = build_role(name="role", change_type_name="change", datafiles=[], users=[])
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    query_func = mocker.Mock(return_value={"roles": [role.model_dump(by_alias=True)]})
    fetched = self_service_roles.fetch_self_service_roles(mocker.Mock(query=query_func))
    assert [user.org_username for user in fetched[0].users] == ["alice"]
    assert role.users == []
    resolver = mocker.patch.object(
        self_service_roles,
        "resolve_role_members",
        side_effect=AssertionError("Context builder must not resolve memberships"),
    )
    assert (
        self_service_roles.change_type_contexts_for_self_service_roles(fetched, [], [])
        == []
    )
    resolver.assert_not_called()


def test_current_bundle_role_validation_does_not_resolve_memberships(
    ldap_endpoint: AsyncMock, mocker: MockerFixture
) -> None:
    from reconcile.change_owners import self_service_roles
    from reconcile.test.change_owners.fixtures import build_role

    role = build_role(name="role", change_type_name="change", datafiles=[], users=[])
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    query_func = mocker.Mock(return_value={"roles": [role.model_dump(by_alias=True)]})
    resolver = mocker.spy(self_service_roles, "resolve_role_members")
    self_service_roles.validate_self_service_roles(mocker.Mock(query=query_func))
    resolver.assert_not_called()
    ldap_endpoint.assert_not_awaited()


def test_gitlab_filters_unmanaged_group_before_resolution(
    ldap_endpoint: AsyncMock, gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    from reconcile import gitlab_members
    from reconcile.gql_definitions.gitlab_members.permissions import (
        PermissionGitlabGroupMembershipV1,
    )

    permission = gql_class_factory(
        PermissionGitlabGroupMembershipV1,
        {"group": "unmanaged", "roles": [{"name": "role", "users": [], "bots": []}]},
    )
    assert permission.roles
    permission.roles[0].member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    assert (
        gitlab_members.get_permissions(
            query_func=mocker.Mock(
                return_value={"permissions": [permission.model_dump(by_alias=True)]}
            ),
            managed_groups={"managed"},
        )
        == []
    )
    ldap_endpoint.assert_not_awaited()


def test_sendgrid_roles_resolve_members_at_fetch_boundary(
    ldap_endpoint: AsyncMock, gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    role = gql_class_factory(
        SendgridRole,
        {"name": "role", "users": [], "sendgrid_accounts": [{"name": "account"}]},
    )
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    query_func = mocker.Mock(return_value={"roles": [role.model_dump(by_alias=True)]})
    fetched = sendgrid_teammates.get_roles(query_func=query_func)
    assert [user.org_username for user in fetched[0].users] == ["alice"]
    resolver = mocker.patch.object(
        sendgrid_teammates,
        "resolve_role_members",
        side_effect=AssertionError("Builder must not resolve memberships"),
    )
    assert [
        user.email
        for user in sendgrid_teammates.fetch_desired_state(fetched)["account"]
    ] == ["alice@redhat.com"]
    resolver.assert_not_called()


def test_automated_actions_instances_resolve_members_at_fetch_boundary(
    ldap_endpoint: AsyncMock, gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    from reconcile.automated_actions.config import integration as module
    from reconcile.gql_definitions.automated_actions.instance import (
        AutomatedActionsInstanceV1,
    )

    instance = gql_class_factory(
        AutomatedActionsInstanceV1,
        {
            "name": "instance",
            "deployment": {"name": "namespace", "delete": False},
            "actions": [
                {
                    "type": "action",
                    "maxOps": 1,
                    "permissions": [
                        {"roles": [{"name": "role", "users": [], "bots": []}]}
                    ],
                }
            ],
        },
    )
    assert (
        instance.actions
        and instance.actions[0].permissions
        and instance.actions[0].permissions[0].roles
    )
    instance.actions[0].permissions[0].roles[0].member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    query_func = mocker.Mock(
        return_value={
            "automated_actions_instances_v1": [instance.model_dump(by_alias=True)]
        }
    )
    integration = AutomatedActionsConfigIntegration(
        AutomatedActionsConfigIntegrationParams(thread_pool_size=1)
    )
    fetched = list(integration.get_automated_actions_instances(query_func=query_func))
    assert fetched[0].actions
    assert fetched[0].actions[0].permissions
    assert fetched[0].actions[0].permissions[0].roles
    assert [
        user.org_username
        for user in fetched[0].actions[0].permissions[0].roles[0].users
    ] == ["alice"]
    resolver = mocker.patch.object(
        module,
        "resolve_role_members",
        side_effect=AssertionError("Compiler must not resolve memberships"),
    )
    assert [
        user.username for user in integration.compile_users(fetched[0].actions)
    ] == ["alice"]
    resolver.assert_not_called()


def test_infrastructure_clusters_resolve_members_at_fetch_boundary(
    ldap_endpoint: AsyncMock, gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    from reconcile import ocm_aws_infrastructure_access as module

    cluster = gql_class_factory(
        InfrastructureCluster,
        {
            "name": "cluster",
            "spec": {"product": module.OCM_PRODUCT_OSD},
            "ocm": {"name": "ocm"},
            "awsInfrastructureAccess": [
                {
                    "accessLevel": "admin",
                    "awsGroup": {
                        "account": {
                            "name": "account",
                            "uid": "123",
                            "automationToken": {"path": "aws/token"},
                        },
                        "roles": [{"name": "role", "users": []}],
                    },
                }
            ],
        },
    )
    assert (
        cluster.aws_infrastructure_access
        and cluster.aws_infrastructure_access[0].aws_group.roles
    )
    cluster.aws_infrastructure_access[0].aws_group.roles[0].member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    mocker.patch.object(module.gql, "get_api").return_value.query.return_value = {
        "clusters": [cluster.model_dump(by_alias=True)]
    }
    fetched = module.get_clusters()
    assert fetched[0].aws_infrastructure_access
    assert fetched[0].aws_infrastructure_access[0].aws_group.roles
    assert [
        user.org_username
        for user in fetched[0].aws_infrastructure_access[0].aws_group.roles[0].users
    ] == ["alice"]
    resolver = mocker.patch.object(
        module,
        "resolve_role_members",
        side_effect=AssertionError("Builder must not resolve memberships"),
    )
    mocker.patch.object(module, "get_namespaces", return_value=[])
    mocker.patch.object(module.queries, "get_aws_accounts", return_value=[])
    mocker.patch.object(module.queries, "get_app_interface_settings", return_value={})
    mocker.patch.object(
        module, "AWSApi"
    ).return_value.__enter__.return_value._get_account_users.return_value = ["alice"]
    assert [grant.user_arn for grant in module.fetch_desired_state(fetched)] == [
        "arn:aws:iam::123:user/alice"
    ]
    resolver.assert_not_called()


@pytest.mark.asyncio
async def test_github_owners_roles_resolve_members_at_fetch_boundary(
    ldap_endpoint: AsyncMock, gql_class_factory: Callable, mocker: MockerFixture
) -> None:
    from reconcile.github_owners_api import (
        GithubOwnersIntegration,
        GithubOwnersIntegrationParams,
    )
    from reconcile.gql_definitions.github_owners_api.roles import RoleV1

    role = gql_class_factory(
        RoleV1,
        {
            "name": "role",
            "users": [],
            "bots": [],
            "permissions": [
                {"service": "github-org-team", "org": "org", "role": "owner"}
            ],
        },
    )
    role.member_sources = [
        build_ldap_membership_source(name="ldap", group="source-team")
    ]
    integration = GithubOwnersIntegration(GithubOwnersIntegrationParams())
    fetched = await integration.get_roles(
        query_func=mocker.Mock(return_value={"roles": [role.model_dump(by_alias=True)]})
    )
    assert [user.github_username for user in fetched[0].users] == ["AliceGH"]


@pytest.mark.asyncio
@pytest.mark.parametrize("getter", ["get_permissions", "get_roles"])
async def test_slack_getters_resolve_members_at_fetch_boundary(
    getter: str,
    ldap_endpoint: AsyncMock,
    gql_class_factory: Callable,
    mocker: MockerFixture,
) -> None:
    from reconcile import slack_usergroups_api as module
    from reconcile.gql_definitions.slack_usergroups_api.permissions import (
        PermissionSlackUsergroupV1,
    )
    from reconcile.gql_definitions.slack_usergroups_api.roles import RoleV1

    integration = module.SlackUsergroupsIntegration(
        module.SlackUsergroupsIntegrationParams(
            workspace_name=None, usergroup_name=None
        )
    )
    ldap_endpoint.return_value.groups[0].members[0].github_username = None
    source = build_ldap_membership_source(name="ldap", group="source-team").model_dump(
        by_alias=True
    )
    if getter == "get_permissions":
        permission = gql_class_factory(
            PermissionSlackUsergroupV1,
            {
                "service": "slack-usergroup",
                "handle": "team",
                "workspace": {"name": "workspace", "managedUsergroups": ["team"]},
                "roles": [{"name": "role", "users": [], "bots": []}],
            },
        )
        assert permission.roles
        permission.roles[0].member_sources = [
            build_ldap_membership_source(name="ldap", group="source-team")
        ]
        fetched = await integration.get_permissions(
            query_func=mocker.Mock(
                return_value={"permissions": [permission.model_dump(by_alias=True)]}
            )
        )
        assert fetched[0].roles
        users = fetched[0].roles[0].users
    else:
        role = gql_class_factory(
            RoleV1,
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
        data = role.model_dump(by_alias=True)
        data["memberSources"] = [source]
        fetched_roles = await integration.get_roles(
            query_func=mocker.Mock(return_value={"roles": [data]})
        )
        users = fetched_roles[0].users
    assert [user.org_username for user in users] == ["alice"]


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize(
    "consumer", ["rolebindings", "clusterrolebindings", "openshift-users", "sendgrid"]
)
def test_unresolved_membership_aborts_before_mutations(
    consumer: str,
    dry_run: bool,
    ldap_endpoint: AsyncMock,
    namespace_role: RoleV1,
    gql_class_factory: Callable,
    mocker: MockerFixture,
) -> None:
    ldap_endpoint.return_value = LdapGroupMembersResponse(groups=[])
    oc_map = mocker.Mock()
    oc_map.clusters.return_value = ["cluster"]
    inventory = mocker.Mock()
    inventory.get_desired.return_value = None
    match consumer:
        case "rolebindings":
            integration = OpenShiftRoleBindingsIntegration(
                OpenShiftRoleBindingsIntegrationParams()
            )
            mocker.patch.object(
                integration, "fetch_current_state", return_value=(inventory, oc_map)
            )
            mocker.patch(
                "reconcile.openshift_bindings.openshift_rolebindings.get_app_interface_roles",
                return_value=[namespace_role],
            )
            apply = mocker.patch(
                "reconcile.openshift_bindings.openshift_rolebindings.ob.realize_data"
            )
            with pytest.raises(RuntimeError, match="could not be resolved"):
                integration.run(dry_run=dry_run)
        case "clusterrolebindings":
            cluster_integration = OpenShiftClusterRoleBindingsIntegration(
                OpenShiftClusterRoleBindingsIntegrationParams()
            )
            mocker.patch.object(
                cluster_integration,
                "fetch_current_state",
                return_value=(inventory, oc_map),
            )
            role = gql_class_factory(
                ClusterRole,
                {
                    "name": "team",
                    "users": [],
                    "access": [
                        {
                            "cluster": {
                                "name": "cluster",
                                "auth": [{"service": "oidc"}],
                            },
                            "clusterRole": "view",
                        }
                    ],
                },
            )
            role.member_sources = [
                build_ldap_membership_source(name="ldap", group="source-team")
            ]
            mocker.patch(
                "reconcile.openshift_bindings.openshift_clusterrolebindings.get_app_interface_clusterroles",
                return_value=[role],
            )
            apply = mocker.patch(
                "reconcile.openshift_bindings.openshift_clusterrolebindings.ob.realize_data"
            )
            with pytest.raises(RuntimeError, match="could not be resolved"):
                cluster_integration.run(dry_run=dry_run)
        case "openshift-users":
            mocker.patch(
                "reconcile.openshift_users.fetch_current_state",
                return_value=(oc_map, [{"cluster": "cluster", "user": "alice"}]),
            )
            mocker.patch(
                "reconcile.openshift_users.get_app_interface_roles",
                return_value=[namespace_role],
            )
            apply = mocker.patch("reconcile.openshift_users.act")
            with pytest.raises(RuntimeError, match="could not be resolved"):
                openshift_users.run(dry_run=dry_run)
        case "sendgrid":
            from reconcile.gql_definitions.sendgrid_teammates.roles import (
                SendgridTeammateRolesQueryData,
            )

            role = gql_class_factory(
                SendgridRole,
                {
                    "name": "team",
                    "users": [],
                    "sendgrid_accounts": [{"name": "account"}],
                },
            )
            role.member_sources = [
                build_ldap_membership_source(name="ldap", group="source-team")
            ]
            mocker.patch(
                "reconcile.sendgrid_teammates.roles_query",
                return_value=SendgridTeammateRolesQueryData(roles=[role]),
            )
            mocker.patch(
                "reconcile.sendgrid_teammates.queries.get_app_interface_settings",
                return_value={},
            )
            mocker.patch("reconcile.sendgrid_teammates.SecretReader")
            apply = mocker.patch("reconcile.sendgrid_teammates.act")
            with pytest.raises(RuntimeError, match="could not be resolved"):
                sendgrid_teammates.run(dry_run=dry_run)
        case _:
            pytest.fail(f"Unknown consumer {consumer}")
    apply.assert_not_called()
