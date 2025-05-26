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
    AutomatedActionActionListArgumentV1,
    AutomatedActionActionListV1,
    AutomatedActionOpenshiftWorkloadRestartArgumentV1,
    AutomatedActionOpenshiftWorkloadRestartArgumentV1_NamespaceV1,
    AutomatedActionOpenshiftWorkloadRestartArgumentV1_NamespaceV1_ClusterV1,
    AutomatedActionOpenshiftWorkloadRestartV1,
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
def actions() -> list[AutomatedActionV1]:
    return [
        # An action with no arguments
        AutomatedActionV1(
            type="create-token",
            retries=1,
            maxOps=1,
            permissions=[
                PermissionAutomatedActionsV1(
                    roles=[
                        RoleV1(
                            name="role-1",
                            users=[UserV1(org_username="user1")],
                            bots=[BotV1(org_username="bot1")],
                            expirationDate=None,
                        )
                    ],
                )
            ],
        ),
        AutomatedActionActionListV1(
            type="action-list",
            retries=0,
            maxOps=0,
            permissions=[
                PermissionAutomatedActionsV1(
                    roles=[
                        RoleV1(
                            name="role-2",
                            users=[UserV1(org_username="user1")],
                            bots=[],
                            expirationDate=None,
                        )
                    ],
                )
            ],
            action_list_arguments=[
                AutomatedActionActionListArgumentV1(
                    action_user=".*", max_age_minutes=None
                )
            ],
        ),
        AutomatedActionOpenshiftWorkloadRestartV1(
            type="openshift-workload-restart",
            retries=2,
            maxOps=5,
            permissions=[
                PermissionAutomatedActionsV1(
                    roles=[
                        RoleV1(
                            name="role-2",
                            users=[UserV1(org_username="user1")],
                            bots=[],
                            expirationDate=None,
                        )
                    ],
                )
            ],
            openshift_workload_restart_arguments=[
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
                )
            ],
        ),
    ]


@pytest.fixture
def automated_actions_users() -> list[AutomatedActionsUser]:
    return [
        AutomatedActionsUser(username="user1", roles={"role-1", "role-2"}),
        AutomatedActionsUser(username="bot1", roles={"role-1"}),
    ]


@pytest.fixture
def automated_actions_roles() -> AutomatedActionRoles:
    return {
        "role-1": [
            AutomatedActionsPolicy(obj="create-token", max_ops=1, params={}),
        ],
        "role-2": [
            AutomatedActionsPolicy(
                obj="action-list",
                max_ops=0,
                params={"action_user": ".*"},
            ),
            AutomatedActionsPolicy(
                obj="openshift-workload-restart",
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
  role-1:
  - max_ops: 1
    obj: create-token
    params: {}
  role-2:
  - max_ops: 0
    obj: action-list
    params:
      action_user: .*
  - max_ops: 5
    obj: openshift-workload-restart
    params:
      cluster: ^cluster$
      kind: Deployment|Pod
      name: shaver.*
      namespace: ^namespace$
users:
  bot1:
  - role-1
  user1:
  - role-1
  - role-2
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
        actions=None,
    )
