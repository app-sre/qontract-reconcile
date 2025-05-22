from collections.abc import Callable, Mapping
from typing import Any

import pytest

from reconcile.automated_actions.config.integration import (
    AutomatedActionRoles,
    AutomatedActionsConfigIntegration,
    AutomatedActionsConfigIntegrationParams,
    AutomatedActionsPolicy,
    AutomatedActionsUser,
)
from reconcile.gql_definitions.automated_actions.instance import (
    AutomatedActionArgumentOpenshiftV1,
    AutomatedActionArgumentOpenshiftV1_NamespaceV1,
    AutomatedActionArgumentOpenshiftV1_NamespaceV1_ClusterV1,
    AutomatedActionsInstanceV1,
    AutomatedActionV1,
    BotV1,
    NamespaceV1,
    PermissionAutomatedActionsV1,
    RoleV1,
    UserV1,
)
from reconcile.gql_definitions.fragments.oc_connection_cluster import (
    OcConnectionCluster,
)
from reconcile.test.fixtures import Fixtures


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("automated_actions")


@pytest.fixture
def intg() -> AutomatedActionsConfigIntegration:
    return AutomatedActionsConfigIntegration(
        AutomatedActionsConfigIntegrationParams(thread_pool_size=1, use_jump_host=False)
    )


@pytest.fixture
def raw_fixture_data(fx: Fixtures) -> dict[str, Any]:
    return fx.get_anymarkup("instances.yml")


@pytest.fixture
def query_func(
    data_factory: Callable[
        [type[AutomatedActionsInstanceV1], Mapping[str, Any]], Mapping[str, Any]
    ],
    raw_fixture_data: dict[str, Any],
) -> Callable:
    def q(*args: Any, **kwargs: Any) -> dict:
        return {
            "automated_actions_instances_v1": [
                data_factory(AutomatedActionsInstanceV1, item)
                for item in raw_fixture_data["automated_actions_instances_v1"]
            ]
        }

    return q


@pytest.fixture
def instances(
    query_func: Callable,
    intg: AutomatedActionsConfigIntegration,
) -> list[AutomatedActionsInstanceV1]:
    return list(intg.get_automated_actions_instances(query_func))


@pytest.fixture
def permissions() -> list[PermissionAutomatedActionsV1]:
    return [
        PermissionAutomatedActionsV1(
            roles=[
                RoleV1(
                    name="role",
                    users=[UserV1(org_username="user1")],
                    bots=[BotV1(org_username="bot1")],
                    expirationDate=None,
                )
            ],
            arguments=None,
            action=AutomatedActionV1(operationId="action", retries=1, maxOps=1),
        ),
        PermissionAutomatedActionsV1(
            roles=[
                RoleV1(
                    name="another-role-with-args",
                    users=[UserV1(org_username="user1")],
                    bots=[],
                    expirationDate=None,
                )
            ],
            arguments=[
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
                )
            ],
            action=AutomatedActionV1(operationId="action", retries=1, maxOps=5),
        ),
    ]


@pytest.fixture
def automated_actions_users() -> list[AutomatedActionsUser]:
    return [
        AutomatedActionsUser(
            username="user1", roles={"another-role-with-args", "role"}
        ),
        AutomatedActionsUser(username="bot1", roles={"role"}),
    ]


@pytest.fixture
def automated_actions_roles() -> AutomatedActionRoles:
    return {
        "role": [
            AutomatedActionsPolicy(sub="role", obj="action", max_ops=1, params={}),
        ],
        "another-role-with-args": [
            AutomatedActionsPolicy(
                sub="another-role-with-args",
                obj="action",
                max_ops=5,
                params={
                    "cluster": "^cluster$",
                    "namespace": "^namespace$",
                    "kind": "Deployment|Pod",
                    "name": "shaver.*",
                },
            ),
        ],
    }


@pytest.fixture
def policy_file() -> str:
    return """roles:
  another-role-with-args:
  - max_ops: 5
    obj: action
    params:
      cluster: ^cluster$
      kind: Deployment|Pod
      name: shaver.*
      namespace: ^namespace$
    sub: another-role-with-args
  role:
  - max_ops: 1
    obj: action
    params: {}
    sub: role
users:
  bot1:
  - role
  user1:
  - another-role-with-args
  - role
"""


@pytest.fixture
def instance() -> AutomatedActionsInstanceV1:
    return AutomatedActionsInstanceV1(
        name="instance",
        deployment=NamespaceV1(
            name="namespace",
            delete=False,
            clusterAdmin=None,
            cluster=OcConnectionCluster(
                name="cluster",
                serverUrl="https://cluster.example.com:6443",
                internal=None,
                automationToken=None,
                insecureSkipTLSVerify=None,
                jumpHost=None,
                clusterAdminAutomationToken=None,
                disable=None,
            ),
        ),
        permissions=None,
    )
