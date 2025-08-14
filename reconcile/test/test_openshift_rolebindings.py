"""Tests for reconcile.openshift_rolebindings module."""

import operator

from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.app_interface_roles import (
    AccessV1,
    BotV1,
    ClusterAuthV1,
    ClusterV1,
    NamespaceV1,
    RoleV1,
    UserV1,
)
from reconcile.openshift_rolebindings import (
    OCResource,
    RoleBindingSpec,
    fetch_desired_state,
)
from reconcile.utils.openshift_resource import OpenshiftResource as OR


def get_app_interface_test_roles() -> list[RoleV1]:
    return [
        RoleV1(
            name="test-role5",
            users=[
                UserV1(
                    org_username="test-org-user", github_username="test-github-user"
                ),
            ],
            bots=[
                BotV1(openshift_serviceaccount="test-namespace5/test-serviceaccount")
            ],
            access=[
                AccessV1(
                    namespace=NamespaceV1(
                        name="test-namespace5",
                        clusterAdmin=False,
                        managedRoles=True,
                        cluster=ClusterV1(
                            name="test-cluster5", auth=[ClusterAuthV1(service="rhidp")]
                        ),
                        delete=False,
                    ),
                    role="test-role5",
                    clusterRole=None,
                ),
            ],
            expirationDate=None,
        ),
        RoleV1(
            name="test-role",
            users=[
                UserV1(
                    org_username="test-org-user", github_username="test-github-user"
                ),
                UserV1(
                    org_username="test-org-user-2", github_username="test-github-user-2"
                ),
            ],
            bots=[],
            access=[
                AccessV1(
                    namespace=NamespaceV1(
                        name="test-namespace",
                        clusterAdmin=False,
                        managedRoles=True,
                        cluster=ClusterV1(
                            name="test-cluster", auth=[ClusterAuthV1(service="rhidp")]
                        ),
                        delete=False,
                    ),
                    role="test-role-access",
                    clusterRole=None,
                ),
                AccessV1(
                    namespace=NamespaceV1(
                        name="test-namespace",
                        clusterAdmin=True,
                        managedRoles=True,
                        cluster=ClusterV1(
                            name="test-cluster2",
                            auth=[
                                ClusterAuthV1(service="rhidp"),
                                ClusterAuthV1(service="github-org"),
                            ],
                        ),
                        delete=False,
                    ),
                    role=None,
                    clusterRole="test-role-access",
                ),
            ],
            expirationDate=None,
        ),
        RoleV1(
            name="expiredtest-role-2",
            users=[
                UserV1(
                    org_username="test-org-user-3",
                    github_username="test-github-user-3",
                )
            ],
            bots=[],
            access=[
                AccessV1(
                    namespace=NamespaceV1(
                        name="test-namespace-2",
                        clusterAdmin=False,
                        managedRoles=True,
                        cluster=ClusterV1(
                            name="test-cluster-2", auth=[ClusterAuthV1(service="rhidp")]
                        ),
                        delete=False,
                    ),
                    role="test-role-access-2",
                    clusterRole=None,
                )
            ],
            expirationDate="2023-07-10",
        ),
    ]


def test_fetch_desired_state_without_oc_map(mocker: MockerFixture) -> None:
    mocker.patch(
        "reconcile.openshift_rolebindings.get_app_interface_roles"
    ).return_value = get_app_interface_test_roles()
    assert sorted(
        fetch_desired_state(None, None), key=operator.itemgetter("cluster", "user")
    ) == [
        {
            "cluster": "test-cluster",
            "user": "test-org-user",
        },
        {
            "cluster": "test-cluster",
            "user": "test-org-user-2",
        },
        {
            "cluster": "test-cluster2",
            "user": "test-github-user",
        },
        {
            "cluster": "test-cluster2",
            "user": "test-github-user-2",
        },
        {
            "cluster": "test-cluster2",
            "user": "test-org-user",
        },
        {
            "cluster": "test-cluster2",
            "user": "test-org-user-2",
        },
        {
            "cluster": "test-cluster5",
            "user": "test-org-user",
        },
    ]


def test_get_oc_resources() -> None:
    test_role = get_app_interface_test_roles()
    role_binding_spec_list = RoleBindingSpec.create_rb_specs_from_role(
        test_role[0], None, None
    )
    oc_resources = role_binding_spec_list[0].get_oc_resources()
    assert len(oc_resources) == 2
    assert oc_resources[0] == OCResource(
        resource=OR(
            integration="openshift-rolebindings",
            integration_version="0.3.0",
            error_details="test-role5-test-org-user",
            body={
                "kind": "RoleBinding",
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "metadata": {
                    "name": "test-role5-test-org-user",
                },
                "roleRef": {
                    "kind": "ClusterRole",
                    "name": "test-role5",
                },
                "subjects": [
                    {
                        "kind": "User",
                        "name": "test-org-user",
                    }
                ],
            },
        ),
        resource_name="test-role5-test-org-user",
        privileged=False,
    )
    assert oc_resources[1] == OCResource(
        resource=OR(
            integration="openshift-rolebindings",
            integration_version="0.3.0",
            error_details="test-role5-test-namespace5-test-serviceaccount",
            body={
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "RoleBinding",
                "metadata": {
                    "name": "test-role5-test-namespace5-test-serviceaccount",
                },
                "roleRef": {
                    "kind": "ClusterRole",
                    "name": "test-role5",
                },
                "subjects": [
                    {
                        "kind": "ServiceAccount",
                        "name": "test-serviceaccount",
                        "namespace": "test-namespace5",
                    },
                ],
            },
        ),
        resource_name="test-role5-test-namespace5-test-serviceaccount",
        privileged=False,
    )
