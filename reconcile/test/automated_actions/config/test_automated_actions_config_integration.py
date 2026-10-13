from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from reconcile.gql_definitions.automated_actions.instance import (
    AutomatedActionOpenshiftWorkloadRestartArgumentV1,
    AutomatedActionOpenshiftWorkloadRestartArgumentV1_NamespaceV1,
    AutomatedActionOpenshiftWorkloadRestartArgumentV1_NamespaceV1_ClusterV1,
    AutomatedActionOpenshiftWorkloadRestartArgumentV1_NamespaceV1_ClusterV1_DisableClusterAutomationsV1,
    AutomatedActionsInstanceV1,
    AutomatedActionV1,
    PermissionAutomatedActionsV1,
    RoleV1,
)
from reconcile.test.utils.membershipsources.fixtures import build_ldap_membership_source
from reconcile.utils.oc import OCCli
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.runtime.desired_state_diff import build_desired_state_diff

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_mock import MockerFixture

    from reconcile.automated_actions.config.integration import (
        AutomatedActionRoles,
        AutomatedActionsConfigIntegration,
        AutomatedActionsUser,
    )


def test_automated_actions_config_get_early_exit_desired_state(
    query_func: Callable,
    intg: AutomatedActionsConfigIntegration,
) -> None:
    state = intg.get_early_exit_desired_state(query_func=query_func)
    assert state is not None
    assert "automated_actions_instances" in state


def test_automated_actions_early_exit_keeps_membership_source_configuration(
    mocker: MockerFixture,
    intg: AutomatedActionsConfigIntegration,
    instance: AutomatedActionsInstanceV1,
) -> None:
    role = RoleV1(
        name="team",
        users=[],
        bots=[],
        memberSources=[build_ldap_membership_source(name="ldap", group="source-team")],
        expirationDate=None,
    )
    instance.actions = [
        AutomatedActionV1(
            type="action",
            maxOps=1,
            permissions=[PermissionAutomatedActionsV1(roles=[role])],
        )
    ]
    mocker.patch.object(
        intg, "_query_automated_actions_instances", return_value=iter([instance])
    )
    resolver = mocker.patch(
        "reconcile.automated_actions.config.integration.resolve_role_members"
    )
    before = intg.get_early_exit_desired_state(query_func=mocker.Mock())
    assert before == {"automated_actions_instances": [instance.model_dump()]}
    assert build_desired_state_diff(None, before, before).can_exit_early()
    assert role.member_sources is not None
    role.member_sources[0].group = "another-team"
    mocker.patch.object(
        intg, "_query_automated_actions_instances", return_value=iter([instance])
    )
    after = intg.get_early_exit_desired_state(query_func=mocker.Mock())
    assert after is not None
    assert not build_desired_state_diff(None, before, after).can_exit_early()
    resolver.assert_not_called()


def test_automated_actions_config_get_automated_actions_instances(
    gql_class_factory: Callable,
    instances: list[AutomatedActionsInstanceV1],
) -> None:
    assert instances == [
        gql_class_factory(
            AutomatedActionsInstanceV1,
            {
                "name": "automated-actions-prod",
                "deployment": {
                    "name": "automated-actions",
                    "cluster": {
                        "name": "cluster",
                        "serverUrl": "https://cluster.example.com:6443",
                        "internal": False,
                        "automationToken": {
                            "path": "vault_path",
                            "field": "token",
                        },
                    },
                },
                "actions": [
                    {
                        "type": "openshift-workload-restart",
                        "permissions": [
                            {
                                "roles": [
                                    {
                                        "name": "app-sre",
                                        "users": [
                                            {"org_username": "user1"},
                                            {"org_username": "user2"},
                                        ],
                                        "bots": [{"org_username": "bot1"}],
                                    }
                                ]
                            }
                        ],
                        "maxOps": 2,
                        "openshift_workload_restart_arguments": [
                            {
                                "namespace": {
                                    "name": "namespace",
                                    "cluster": {"name": "cluster", "disable": None},
                                },
                                "kind": "Deployment|Pod",
                                "name": "shaver.*",
                            }
                        ],
                    },
                    {
                        "type": "noop",
                        "permissions": [
                            {
                                "roles": [
                                    {
                                        "name": "app-sre",
                                        "users": [
                                            {"org_username": "user1"},
                                            {"org_username": "user2"},
                                        ],
                                        "bots": [{"org_username": "bot1"}],
                                    }
                                ]
                            }
                        ],
                        "maxOps": 0,
                    },
                    {
                        "type": "action-list",
                        "permissions": [
                            {
                                "roles": [
                                    {
                                        "name": "app-sre",
                                        "users": [
                                            {"org_username": "user1"},
                                            {"org_username": "user2"},
                                        ],
                                        "bots": [{"org_username": "bot1"}],
                                    }
                                ]
                            }
                        ],
                        "maxOps": 1,
                        "action_list_arguments": [
                            {
                                "action_user": "user1",
                                "max_age_minutes": None,
                            }
                        ],
                    },
                    {
                        "type": "action-detail",
                        "permissions": [
                            {
                                "roles": [
                                    {
                                        "name": "app-sre",
                                        "users": [
                                            {"org_username": "user1"},
                                            {"org_username": "user2"},
                                        ],
                                        "bots": [{"org_username": "bot1"}],
                                    }
                                ]
                            }
                        ],
                        "maxOps": 0,
                        "action_detail_arguments": [{"owner": ".*"}],
                    },
                    {
                        "type": "action-cancel",
                        "permissions": [
                            {
                                "roles": [
                                    {
                                        "name": "app-sre",
                                        "users": [
                                            {"org_username": "user1"},
                                            {"org_username": "user2"},
                                        ],
                                        "bots": [{"org_username": "bot1"}],
                                    }
                                ]
                            }
                        ],
                        "maxOps": 0,
                        "action_cancel_arguments": [{"owner": ".*"}],
                    },
                ],
            },
        )
    ]


@pytest.mark.parametrize(
    "argument, expected",
    [
        (
            AutomatedActionOpenshiftWorkloadRestartArgumentV1(
                kind="Deployment|Pod",
                name="shaver.*",
                namespace=AutomatedActionOpenshiftWorkloadRestartArgumentV1_NamespaceV1(
                    name="namespace",
                    delete=False,
                    cluster=AutomatedActionOpenshiftWorkloadRestartArgumentV1_NamespaceV1_ClusterV1(
                        name="cluster", disable=None
                    ),
                ),
            ),
            True,
        ),
        # deleted namespace
        (
            AutomatedActionOpenshiftWorkloadRestartArgumentV1(
                kind="Deployment|Pod",
                name="shaver.*",
                namespace=AutomatedActionOpenshiftWorkloadRestartArgumentV1_NamespaceV1(
                    name="namespace",
                    delete=True,
                    cluster=AutomatedActionOpenshiftWorkloadRestartArgumentV1_NamespaceV1_ClusterV1(
                        name="cluster", disable=None
                    ),
                ),
            ),
            False,
        ),
        # integration disabled
        (
            AutomatedActionOpenshiftWorkloadRestartArgumentV1(
                kind="Deployment|Pod",
                name="shaver.*",
                namespace=AutomatedActionOpenshiftWorkloadRestartArgumentV1_NamespaceV1(
                    name="namespace",
                    delete=False,
                    cluster=AutomatedActionOpenshiftWorkloadRestartArgumentV1_NamespaceV1_ClusterV1(
                        name="cluster",
                        disable=AutomatedActionOpenshiftWorkloadRestartArgumentV1_NamespaceV1_ClusterV1_DisableClusterAutomationsV1(
                            integrations=["automated-actions"]
                        ),
                    ),
                ),
            ),
            False,
        ),
    ],
)
def test_automated_actions_config_is_enabled(
    intg: AutomatedActionsConfigIntegration,
    argument: AutomatedActionOpenshiftWorkloadRestartArgumentV1,
    expected: bool,
) -> None:
    assert intg.is_enabled(argument) == expected


@pytest.mark.parametrize(
    "action, expected",
    [
        # no roles
        (
            AutomatedActionV1(
                type="action",
                maxOps=1,
                permissions=[PermissionAutomatedActionsV1(roles=None)],
            ),
            False,
        ),
        # expired roles
        (
            AutomatedActionV1(
                type="action",
                maxOps=1,
                permissions=[
                    PermissionAutomatedActionsV1(
                        roles=[
                            RoleV1(
                                name="role",
                                users=[],
                                bots=[],
                                expirationDate="1970-01-01",
                                memberSources=None,
                            )
                        ]
                    )
                ],
            ),
            False,
        ),
        # valid
        (
            AutomatedActionV1(
                type="action",
                maxOps=1,
                permissions=[
                    PermissionAutomatedActionsV1(
                        roles=[
                            RoleV1(
                                name="role",
                                users=[],
                                bots=[],
                                expirationDate=None,
                                memberSources=None,
                            )
                        ],
                    )
                ],
            ),
            True,
        ),
    ],
)
def test_automated_actions_config_filter_actions(
    intg: AutomatedActionsConfigIntegration,
    action: AutomatedActionV1,
    expected: bool,
) -> None:
    assert bool(list(intg.filter_actions([action]))) == expected


def test_automated_actions_config_compile_users(
    intg: AutomatedActionsConfigIntegration,
    actions: list[AutomatedActionV1],
    automated_actions_users: list[AutomatedActionsUser],
) -> None:
    assert intg.compile_users(actions) == automated_actions_users


def test_compile_users_initializes_roles_as_a_set(
    intg: AutomatedActionsConfigIntegration,
    actions: list[AutomatedActionV1],
    mocker: MockerFixture,
) -> None:
    from reconcile.automated_actions.config import integration

    constructor = mocker.spy(integration, "AutomatedActionsUser")
    intg.compile_users(actions)
    assert constructor.call_args_list
    assert all(
        isinstance(call.kwargs["roles"], set) for call in constructor.call_args_list
    )


@pytest.mark.parametrize("serialized", [None, "invalid", [], 1])
def test_build_configmap_rejects_non_dictionary_serialization(
    intg: AutomatedActionsConfigIntegration,
    instance: AutomatedActionsInstanceV1,
    mocker: MockerFixture,
    serialized: object,
) -> None:
    mocker.patch(
        "reconcile.automated_actions.config.integration.ApiClient.sanitize_for_serialization",
        return_value=serialized,
    )
    inventory = mocker.Mock(spec=ResourceInventory)
    with pytest.raises(TypeError, match="Serialized ConfigMap must be a dictionary"):
        intg.build_desired_configmap(inventory, instance, name="aa-cm", data="data")
    inventory.initialize_resource_type.assert_not_called()
    inventory.add_desired_resource.assert_not_called()


def test_automated_actions_config_compile_roles(
    intg: AutomatedActionsConfigIntegration,
    actions: list[AutomatedActionV1],
    automated_actions_roles: AutomatedActionRoles,
) -> None:
    assert intg.compile_roles(actions) == automated_actions_roles


def test_automated_actions_config_build_policy_file(
    intg: AutomatedActionsConfigIntegration,
    automated_actions_users: list[AutomatedActionsUser],
    automated_actions_roles: AutomatedActionRoles,
    policy_file: str,
) -> None:
    assert (
        intg.build_policy_file(automated_actions_users, automated_actions_roles)
        == policy_file
    )


def test_automated_actions_config_build_desired_configmap(
    intg: AutomatedActionsConfigIntegration, instance: AutomatedActionsInstanceV1
) -> None:
    ri = ResourceInventory()
    intg.build_desired_configmap(ri, instance, name="aa-cm", data="data")
    for cluster_name, namespace_name, resource_type, resource in ri:
        assert cluster_name == instance.deployment.cluster.name
        assert namespace_name == instance.deployment.name
        assert resource_type == "ConfigMap"
        assert resource["desired"]["aa-cm"].body["data"] == {"roles.yml": "data"}


def test_automated_actions_config_fetch_current_configmap(
    intg: AutomatedActionsConfigIntegration,
    instance: AutomatedActionsInstanceV1,
    mocker: MockerFixture,
) -> None:
    ri = ResourceInventory()
    ri.initialize_resource_type(
        cluster=instance.deployment.cluster.name,
        namespace=instance.deployment.name,
        resource_type="ConfigMap",
    )
    oc = mocker.create_autospec(OCCli)
    oc.get.return_value = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "aa-cm"},
        "data": {"roles.yml": "data"},
    }
    intg.fetch_current_configmap(ri, instance, oc, name="aa-cm")
    for cluster_name, namespace_name, resource_type, resource in ri:
        assert cluster_name == instance.deployment.cluster.name
        assert namespace_name == instance.deployment.name
        assert resource_type == "ConfigMap"
        assert resource["current"]["aa-cm"].body["data"] == {"roles.yml": "data"}
