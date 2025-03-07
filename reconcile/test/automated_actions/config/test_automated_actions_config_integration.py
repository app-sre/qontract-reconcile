from collections.abc import Callable

import pytest
from pytest_mock import MockerFixture

from reconcile.automated_actions.config.integration import (
    AutomatedActionsConfigIntegration,
    AutomatedActionsPolicy,
    AutomatedActionsRole,
)
from reconcile.gql_definitions.automated_actions.instance import (
    AutomatedActionArgumentOpenshiftV1,
    AutomatedActionArgumentOpenshiftV1_NamespaceV1,
    AutomatedActionArgumentOpenshiftV1_NamespaceV1_ClusterV1,
    AutomatedActionArgumentV1,
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
                        "automationToken": {"path": "vault_path", "field": "token"},
                    },
                },
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
                        ],
                        "action": {"operationId": "noop"},
                        "arguments": [],
                    },
                    {
                        "roles": [
                            {
                                "name": "tenant",
                                "users": [
                                    {"org_username": "tenant1"},
                                    {"org_username": "tenant2"},
                                ],
                                "bots": [{"org_username": "bot1"}],
                            }
                        ],
                        "action": {
                            "operationId": "openshift-workload-restart",
                            "retries": 2,
                            "maxOps": 2,
                        },
                        "arguments": [
                            {
                                "type": "openshift",
                                "kind_pattern": "Deployment|Pod",
                                "name_pattern": "shaver.*",
                                "namespace": {
                                    "name": "namespace",
                                    "cluster": {"name": "cluster"},
                                },
                            },
                        ],
                    },
                ],
            },
        )
    ]


@pytest.mark.parametrize(
    "argument, expected",
    [
        (AutomatedActionArgumentV1(type="whatever"), True),
        (
            AutomatedActionArgumentOpenshiftV1(
                type="openshift",
                kind_pattern="Deployment|Pod",
                name_pattern="shaver.*",
                namespace=AutomatedActionArgumentOpenshiftV1_NamespaceV1(
                    name="namespace",
                    delete=False,
                    cluster=AutomatedActionArgumentOpenshiftV1_NamespaceV1_ClusterV1(
                        name="cluster", disable=None
                    ),
                ),
            ),
            True,
        ),
        # deleted namespace
        (
            AutomatedActionArgumentOpenshiftV1(
                type="openshift",
                kind_pattern="Deployment|Pod",
                name_pattern="shaver.*",
                namespace=AutomatedActionArgumentOpenshiftV1_NamespaceV1(
                    name="namespace",
                    delete=True,
                    cluster=AutomatedActionArgumentOpenshiftV1_NamespaceV1_ClusterV1(
                        name="cluster", disable=None
                    ),
                ),
            ),
            False,
        ),
        # integration disabled
        (
            AutomatedActionArgumentOpenshiftV1(
                type="openshift",
                kind_pattern="Deployment|Pod",
                name_pattern="shaver.*",
                namespace=AutomatedActionArgumentOpenshiftV1_NamespaceV1(
                    name="namespace",
                    delete=False,
                    cluster=AutomatedActionArgumentOpenshiftV1_NamespaceV1_ClusterV1(
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
    argument: AutomatedActionArgumentV1,
    expected: bool,
) -> None:
    assert intg._is_enabled(argument) == expected


@pytest.mark.parametrize(
    "permission, expected",
    [
        # no roles
        (
            PermissionAutomatedActionsV1(
                roles=None,
                arguments=None,
                action=AutomatedActionV1(
                    operationId="action", retries=None, maxOps=None
                ),
            ),
            False,
        ),
        # expired roles
        (
            PermissionAutomatedActionsV1(
                roles=[
                    RoleV1(name="role", users=[], bots=[], expirationDate="1970-01-01")
                ],
                arguments=None,
                action=AutomatedActionV1(
                    operationId="action", retries=None, maxOps=None
                ),
            ),
            False,
        ),
        # valid
        (
            PermissionAutomatedActionsV1(
                roles=[RoleV1(name="role", users=[], bots=[], expirationDate=None)],
                arguments=None,
                action=AutomatedActionV1(
                    operationId="action", retries=None, maxOps=None
                ),
            ),
            True,
        ),
    ],
)
def test_automated_actions_config_filter_permissions(
    intg: AutomatedActionsConfigIntegration,
    permission: PermissionAutomatedActionsV1,
    expected: bool,
) -> None:
    assert bool(list(intg._filter_permissions([permission]))) == expected


def test_automated_actions_config_compile_roles(
    intg: AutomatedActionsConfigIntegration,
    permissions: list[PermissionAutomatedActionsV1],
    automated_actions_roles: list[AutomatedActionsRole],
) -> None:
    assert intg._compile_roles(permissions) == automated_actions_roles


def test_automated_actions_config_compile_policies(
    intg: AutomatedActionsConfigIntegration,
    permissions: list[PermissionAutomatedActionsV1],
    automated_actions_policies: list[AutomatedActionsPolicy],
) -> None:
    assert intg._compile_policies(permissions) == automated_actions_policies


def test_automated_actions_config_build_policy_file(
    intg: AutomatedActionsConfigIntegration,
    automated_actions_roles: list[AutomatedActionsRole],
    automated_actions_policies: list[AutomatedActionsPolicy],
    policy_file: str,
) -> None:
    assert (
        intg._build_policy_file(automated_actions_roles, automated_actions_policies)
        == policy_file
    )


def test_automated_actions_config_build_desired_configmap(
    intg: AutomatedActionsConfigIntegration, instance: AutomatedActionsInstanceV1
) -> None:
    ri = ResourceInventory()
    intg._build_desired_configmap(ri, instance, name="aa-cm", data="data")
    for cluster_name, namespace_name, resource_type, resource in ri:
        assert cluster_name == instance.deployment.cluster.name
        assert namespace_name == instance.deployment.name
        assert resource_type == "ConfigMap"
        assert resource["desired"]["aa-cm"].body["data"] == {"policy.yml": "data"}


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
        "data": {"policy.yml": "data"},
    }
    intg._fetch_current_configmap(ri, instance, oc, name="aa-cm")
    for cluster_name, namespace_name, resource_type, resource in ri:
        assert cluster_name == instance.deployment.cluster.name
        assert namespace_name == instance.deployment.name
        assert resource_type == "ConfigMap"
        assert resource["current"]["aa-cm"].body["data"] == {"policy.yml": "data"}
