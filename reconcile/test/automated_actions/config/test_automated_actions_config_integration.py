from collections.abc import Callable

import pytest
from pytest_mock import MockerFixture

from reconcile.automated_actions.config.integration import (
    AutomatedActionRoles,
    AutomatedActionsConfigIntegration,
    AutomatedActionsUser,
)
from reconcile.gql_definitions.automated_actions.instance import (
    AutomatedActionOpenshiftWorkloadRestartArgumentV1,
    AutomatedActionOpenshiftWorkloadRestartArgumentV1_NamespaceV1,
    AutomatedActionOpenshiftWorkloadRestartArgumentV1_NamespaceV1_ClusterV1,
    AutomatedActionsInstanceV1,
    AutomatedActionV1,
    DisableClusterAutomationsV1,
    PermissionAutomatedActionsV1,
    RoleV1,
)
from reconcile.utils.oc import OCCli
from reconcile.utils.openshift_resource import ResourceInventory


def test_automated_actions_config_get_early_exit_desired_state(
    query_func: Callable,
    intg: AutomatedActionsConfigIntegration,
) -> None:
    state = intg.get_early_exit_desired_state(query_func=query_func)
    assert "automated_actions_instances" in state


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
                        "retries": 2,
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
                        "retries": 0,
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
                        "retries": 1,
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
                        disable=DisableClusterAutomationsV1(
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
                retries=1,
                maxOps=1,
                permissions=[PermissionAutomatedActionsV1(roles=None)],
            ),
            False,
        ),
        # expired roles
        (
            AutomatedActionV1(
                type="action",
                retries=1,
                maxOps=1,
                permissions=[
                    PermissionAutomatedActionsV1(
                        roles=[
                            RoleV1(
                                name="role",
                                users=[],
                                bots=[],
                                expirationDate="1970-01-01",
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
                retries=1,
                maxOps=1,
                permissions=[
                    PermissionAutomatedActionsV1(
                        roles=[
                            RoleV1(name="role", users=[], bots=[], expirationDate=None)
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
