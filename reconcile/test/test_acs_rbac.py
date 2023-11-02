import pytest
import copy

from unittest.mock import Mock

from reconcile.acs_rbac import (
    AcsRbacIntegration,
    AcsRbacIntegrationParams,
    AcsRole,
    AcsAccessScope,
    AssignmentPair,
)

from reconcile.gql_definitions.acs.acs_rbac import (
    AcsRbacQueryData,
    UserV1,
    RoleV1,
    OidcPermissionAcsV1,
    NamespaceV1,
    NamespaceV1_ClusterV1,
    ClusterV1,
)

import reconcile.utils.acs_api as acs_api


AUTH_PROVIDER_ID = "6a41743c-792b-11ee-b962-0242ac120002"


@pytest.fixture
def query_data_desired_state() -> AcsRbacQueryData:
    return AcsRbacQueryData(
        acs_rbacs=[
            UserV1(
                org_username="foo",
                roles=[
                    RoleV1(
                        name="app-sre-admin",
                        oidc_permissions=[
                            OidcPermissionAcsV1(
                                name="app-sre-acs-admin",
                                description="admin access to acs instance",
                                service="acs",
                                permission_set="admin",
                                clusters=[],
                                namespaces=[],
                            )
                        ],
                    )
                ],
            ),
            UserV1(
                org_username="bar",
                roles=[
                    RoleV1(
                        name="app-sre-admin",
                        oidc_permissions=[
                            OidcPermissionAcsV1(
                                name="app-sre-acs-admin",
                                description="admin access to acs instance",
                                service="acs",
                                permission_set="admin",
                                clusters=[],
                                namespaces=[],
                            )
                        ],
                    )
                ],
            ),
            UserV1(
                org_username="foofoo",
                roles=[
                    RoleV1(
                        name="tenant-role-a",
                        oidc_permissions=[
                            OidcPermissionAcsV1(
                                name="cluster-analyst",
                                description="analyst access to clusters in acs instance",
                                service="acs",
                                permission_set="analyst",
                                clusters=[
                                    ClusterV1(name="clusterA"),
                                    ClusterV1(name="clusterB"),
                                ],
                                namespaces=[],
                            )
                        ],
                    )
                ],
            ),
            UserV1(
                org_username="barbar",
                roles=[
                    RoleV1(
                        name="tenant-role-a",
                        oidc_permissions=[
                            OidcPermissionAcsV1(
                                name="cluster-analyst",
                                description="analyst access to clusters in acs instance",
                                service="acs",
                                permission_set="analyst",
                                clusters=[
                                    ClusterV1(name="clusterA"),
                                    ClusterV1(name="clusterB"),
                                ],
                                namespaces=[],
                            )
                        ],
                    )
                ],
            ),
            UserV1(
                org_username="foobar",
                roles=[
                    RoleV1(
                        name="tenant-role-b",
                        oidc_permissions=[
                            OidcPermissionAcsV1(
                                name="service-vuln-admin",
                                description="vuln-admin access to service namespaces in acs instance",
                                service="acs",
                                permission_set="vuln-admin",
                                clusters=[],
                                namespaces=[
                                    NamespaceV1(
                                        name="serviceA-stage",
                                        cluster=NamespaceV1_ClusterV1(
                                            name="stage-cluster"
                                        ),
                                    ),
                                    NamespaceV1(
                                        name="serviceA-prod",
                                        cluster=NamespaceV1_ClusterV1(
                                            name="prod-cluster"
                                        ),
                                    ),
                                ],
                            )
                        ],
                    )
                ],
            ),
        ]
    )


@pytest.fixture
def modeled_acs_roles() -> list[AcsRole]:
    return [
        AcsRole(
            name="app-sre-acs-admin",
            description="admin access to acs instance",
            assignments=[
                AssignmentPair(key="org_username", value="foo"),
                AssignmentPair(key="org_username", value="bar"),
            ],
            permission_set_name="Admin",
            access_scope=AcsAccessScope(
                name="Unrestricted",
                description="Access to all clusters and namespaces",
                clusters=[],
                namespaces=[],
            ),
            system_default=False,
        ),
        AcsRole(
            name="cluster-analyst",
            description="analyst access to clusters in acs instance",
            assignments=[
                AssignmentPair(key="org_username", value="foofoo"),
                AssignmentPair(key="org_username", value="barbar"),
            ],
            permission_set_name="Analyst",
            access_scope=AcsAccessScope(
                name="cluster-analyst",
                description="analyst access to clusters in acs instance",
                clusters=["clusterA", "clusterB"],
                namespaces=[],
            ),
            system_default=False,
        ),
        AcsRole(
            name="service-vuln-admin",
            description="vuln-admin access to service namespaces in acs instance",
            assignments=[AssignmentPair(key="org_username", value="foobar")],
            permission_set_name="Vulnerability Management Admin",
            access_scope=AcsAccessScope(
                name="service-vuln-admin",
                description="vuln-admin access to service namespaces in acs instance",
                clusters=[],
                namespaces=[
                    {"clusterName": "stage-cluster", "namespaceName": "serviceA-stage"},
                    {"clusterName": "prod-cluster", "namespaceName": "serviceA-prod"},
                ],
            ),
            system_default=False,
        ),
    ]


@pytest.fixture
def api_response_roles() -> list[acs_api.Role]:
    return [
        acs_api.Role(
            api_data={
                "name": "app-sre-acs-admin",
                "permissionSetId": "1",
                "accessScopeId": "1",
                "description": "admin access to acs instance",
                "system_default": False,
            }
        ),
        acs_api.Role(
            api_data={
                "name": "cluster-analyst",
                "permissionSetId": "2",
                "accessScopeId": "2",
                "description": "analyst access to clusters in acs instance",
                "system_default": False,
            }
        ),
        acs_api.Role(
            api_data={
                "name": "service-vuln-admin",
                "permissionSetId": "3",
                "accessScopeId": "3",
                "description": "vuln-admin access to service namespaces in acs instance",
                "system_default": False,
            }
        ),
    ]


@pytest.fixture
def api_response_groups() -> list[acs_api.Group]:
    return [
        acs_api.Group(
            api_data={
                "roleName": "app-sre-acs-admin",
                "props": {
                    "id": "1",
                    "authProviderId": AUTH_PROVIDER_ID,
                    "key": "org_username",
                    "value": "foo",
                },
            }
        ),
        acs_api.Group(
            api_data={
                "roleName": "app-sre-acs-admin",
                "props": {
                    "id": "2",
                    "authProviderId": AUTH_PROVIDER_ID,
                    "key": "org_username",
                    "value": "bar",
                },
            }
        ),
        acs_api.Group(
            api_data={
                "roleName": "cluster-analyst",
                "props": {
                    "id": "3",
                    "authProviderId": AUTH_PROVIDER_ID,
                    "key": "org_username",
                    "value": "foofoo",
                },
            }
        ),
        acs_api.Group(
            api_data={
                "roleName": "cluster-analyst",
                "props": {
                    "id": "4",
                    "authProviderId": AUTH_PROVIDER_ID,
                    "key": "org_username",
                    "value": "barbar",
                },
            }
        ),
        acs_api.Group(
            api_data={
                "roleName": "service-vuln-admin",
                "props": {
                    "id": "5",
                    "authProviderId": AUTH_PROVIDER_ID,
                    "key": "org_username",
                    "value": "foobar",
                },
            }
        ),
    ]


@pytest.fixture
def api_response_access_scopes() -> list[acs_api.AccessScope]:
    return [
        acs_api.AccessScope(
            api_data={
                "id": "1",
                "name": "Unrestricted",
                "description": "Access to all clusters and namespaces",
                "rules": None,
            }
        ),
        acs_api.AccessScope(
            api_data={
                "id": "2",
                "name": "cluster-analyst",
                "description": "analyst access to clusters in acs instance",
                "rules": {
                    "includedClusters": ["clusterA", "clusterB"],
                    "includedNamespaces": [],
                },
            }
        ),
        acs_api.AccessScope(
            api_data={
                "id": "3",
                "name": "service-vuln-admin",
                "description": "vuln-admin access to service namespaces in acs instance",
                "rules": {
                    "includedClusters": [],
                    "includedNamespaces": [
                        {
                            "clusterName": "stage-cluster",
                            "namespaceName": "serviceA-stage",
                        },
                        {
                            "clusterName": "prod-cluster",
                            "namespaceName": "serviceA-prod",
                        },
                    ],
                },
            }
        ),
    ]


@pytest.fixture
def api_response_permission_sets() -> list[acs_api.PermissionSet]:
    return [
        acs_api.PermissionSet(
            api_data={
                "id": "1",
                "name": "Admin",
            }
        ),
        acs_api.PermissionSet(
            api_data={
                "id": "2",
                "name": "Analyst",
            }
        ),
        acs_api.PermissionSet(
            api_data={
                "id": "3",
                "name": "Vulnerability Management Admin",
            }
        ),
    ]


def test_get_desired_state(mocker, query_data_desired_state, modeled_acs_roles):
    integration = AcsRbacIntegration(AcsRbacIntegrationParams(thread_pool_size=10))

    query_func = mocker.patch("reconcile.acs_rbac.acs_rbac_query", autospec=True)
    query_func.return_value = query_data_desired_state

    result = integration.get_desired_state(query_func)

    assert result == modeled_acs_roles


def test_get_current_state(
    modeled_acs_roles,
    api_response_roles,
    api_response_groups,
    api_response_access_scopes,
    api_response_permission_sets,
):
    acs_mock = Mock()

    acs_mock.get_roles.return_value = api_response_roles
    acs_mock.get_groups.return_value = api_response_groups
    acs_mock.get_access_scope_by_id.side_effect = api_response_access_scopes
    acs_mock.get_permission_set_by_id.side_effect = api_response_permission_sets

    integration = AcsRbacIntegration(AcsRbacIntegrationParams(thread_pool_size=10))
    result = integration.get_current_state(acs_mock, AUTH_PROVIDER_ID)

    assert result == modeled_acs_roles
