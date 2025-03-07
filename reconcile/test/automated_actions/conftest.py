from collections.abc import Callable, Mapping
from typing import Any

import pytest
import yaml

from reconcile.automated_actions.config.integration import (
    AutomatedActionsConfigIntegration,
    AutomatedActionsConfigIntegrationParams,
    AutomatedActionsPolicy,
    AutomatedActionsRole,
)
from reconcile.gql_definitions.automated_actions.instance import (
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
            action=AutomatedActionV1(operationId="action", retries=None, maxOps=None),
        ),
        PermissionAutomatedActionsV1(
            roles=[
                RoleV1(
                    name="another-role",
                    users=[UserV1(org_username="user1")],
                    bots=[BotV1(org_username="bot1")],
                    expirationDate=None,
                )
            ],
            arguments=None,
            action=AutomatedActionV1(operationId="action", retries=None, maxOps=None),
        ),
    ]


@pytest.fixture
def automated_actions_roles() -> list[AutomatedActionsRole]:
    return [
        AutomatedActionsRole(user="user1", role="role"),
        AutomatedActionsRole(user="bot1", role="role"),
        AutomatedActionsRole(user="user1", role="another-role"),
        AutomatedActionsRole(user="bot1", role="another-role"),
    ]


@pytest.fixture
def automated_actions_policies() -> list[AutomatedActionsPolicy]:
    return [
        AutomatedActionsPolicy(sub="role", obj="action", params={}),
        AutomatedActionsPolicy(sub="another-role", obj="action", params={}),
    ]


@pytest.fixture
def policy_file() -> str:
    return yaml.dump({
        "g": [
            {
                "role": "role",
                "user": "user1",
            },
            {
                "role": "role",
                "user": "bot1",
            },
            {
                "role": "another-role",
                "user": "user1",
            },
            {
                "role": "another-role",
                "user": "bot1",
            },
        ],
        "p": [
            {
                "obj": "action",
                "params": {},
                "sub": "role",
            },
            {
                "obj": "action",
                "params": {},
                "sub": "another-role",
            },
        ],
    })


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
