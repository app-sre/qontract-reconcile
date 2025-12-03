"""Tests for reconcile.openshift_clusterrolebindings module."""

from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.app_interface_clusterrole import (
    AccessV1,
    BotV1,
    ClusterAuthV1,
    ClusterV1,
    RoleV1,
    UserV1,
)
from reconcile.openshift_clusterrolebindings import (
    NAMESPACE_CLUSTER_SCOPE,
    ClusterRoleBindingSpec,
    OCResource,
    fetch_desired_state_v2,
)
from reconcile.utils.openshift_resource import (
    OpenshiftResource as OR,
)
from reconcile.utils.openshift_resource import (
    ResourceInventory,
)


def get_app_interface_test_clusterroles() -> list[RoleV1]:
    return [
        RoleV1(
            name="test-clusterrole5",
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
                    cluster=ClusterV1(
                        name="test-cluster5", auth=[ClusterAuthV1(service="rhidp")]
                    ),
                    clusterRole="test-clusterrole5",
                ),
            ],
            expirationDate=None,
        ),
        RoleV1(
            name="test-clusterrole",
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
                    cluster=ClusterV1(
                        name="test-cluster", auth=[ClusterAuthV1(service="rhidp")]
                    ),
                    clusterRole="test-clusterrole-access",
                ),
                AccessV1(
                    cluster=ClusterV1(
                        name="test-cluster2",
                        auth=[
                            ClusterAuthV1(service="rhidp"),
                            ClusterAuthV1(service="github-org"),
                        ],
                    ),
                    clusterRole="test-clusterrole-access",
                ),
            ],
            expirationDate=None,
        ),
        RoleV1(
            name="expired-test-clusterrole-2",
            users=[
                UserV1(
                    org_username="test-org-user-3",
                    github_username="test-github-user-3",
                )
            ],
            bots=[],
            access=[
                AccessV1(
                    cluster=ClusterV1(
                        name="test-cluster-2", auth=[ClusterAuthV1(service="rhidp")]
                    ),
                    clusterRole="test-clusterrole-access-2",
                )
            ],
            expirationDate="2023-07-10",
        ),
    ]


def test_get_oc_resources() -> None:
    test_clusterrole = get_app_interface_test_clusterroles()
    cluster_role_binding_spec_list = (
        ClusterRoleBindingSpec.create_cluster_role_binding_specs(test_clusterrole[0])
    )
    oc_resources = cluster_role_binding_spec_list[0].get_oc_resources()
    assert len(oc_resources) == 2
    assert oc_resources[0] == OCResource(
        resource=OR(
            integration="openshift-clusterrolebindings",
            integration_version="0.1.0",
            error_details="test-clusterrole5-test-org-user",
            body={
                "kind": "ClusterRoleBinding",
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "metadata": {
                    "name": "test-clusterrole5-test-org-user",
                },
                "roleRef": {
                    "kind": "ClusterRole",
                    "name": "test-clusterrole5",
                },
                "subjects": [
                    {
                        "kind": "User",
                        "name": "test-org-user",
                    }
                ],
            },
        ),
        resource_name="test-clusterrole5-test-org-user",
    )
    assert oc_resources[1] == OCResource(
        resource=OR(
            integration="openshift-clusterrolebindings",
            integration_version="0.1.0",
            error_details="test-clusterrole5-test-namespace5-test-serviceaccount",
            body={
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "ClusterRoleBinding",
                "metadata": {
                    "name": "test-clusterrole5-test-namespace5-test-serviceaccount",
                },
                "roleRef": {
                    "kind": "ClusterRole",
                    "name": "test-clusterrole5",
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
        resource_name="test-clusterrole5-test-namespace5-test-serviceaccount",
    )


def test_fetch_desired_state_v2_with_filtered_clusters(
    mocker: MockerFixture,
) -> None:
    ri = ResourceInventory()
    ri.initialize_resource_type(
        "test-cluster5",
        NAMESPACE_CLUSTER_SCOPE,
        "ClusterRoleBinding.rbac.authorization.k8s.io",
    )
    ri.initialize_resource_type(
        "test-cluster",
        NAMESPACE_CLUSTER_SCOPE,
        "ClusterRoleBinding.rbac.authorization.k8s.io",
    )
    mocker.patch(
        "reconcile.openshift_clusterrolebindings.get_app_interface_clusterroles"
    ).return_value = get_app_interface_test_clusterroles()
    fetch_desired_state_v2(ri, allowed_clusters={"test-cluster5"})
    assert ri.get_desired(
        "test-cluster5",
        NAMESPACE_CLUSTER_SCOPE,
        "ClusterRoleBinding.rbac.authorization.k8s.io",
        "test-clusterrole5-test-org-user",
    )
    assert not ri.get_desired(
        "test-cluster",
        NAMESPACE_CLUSTER_SCOPE,
        "ClusterRoleBinding.rbac.authorization.k8s.io",
        "test-clusterrole5-test-org-user",
    )


def test_fetch_desired_state_v2_without_filtered_clusters(
    mocker: MockerFixture,
) -> None:
    ri = ResourceInventory()
    ri.initialize_resource_type(
        "test-cluster5",
        NAMESPACE_CLUSTER_SCOPE,
        "ClusterRoleBinding.rbac.authorization.k8s.io",
    )
    ri.initialize_resource_type(
        "test-cluster2",
        NAMESPACE_CLUSTER_SCOPE,
        "ClusterRoleBinding.rbac.authorization.k8s.io",
    )
    ri.initialize_resource_type(
        "test-cluster",
        NAMESPACE_CLUSTER_SCOPE,
        "ClusterRoleBinding.rbac.authorization.k8s.io",
    )
    mocker.patch(
        "reconcile.openshift_clusterrolebindings.get_app_interface_clusterroles"
    ).return_value = get_app_interface_test_clusterroles()
    fetch_desired_state_v2(
        ri, allowed_clusters={"test-cluster5", "test-cluster", "test-cluster2"}
    )
    assert ri.get_desired(
        "test-cluster5",
        NAMESPACE_CLUSTER_SCOPE,
        "ClusterRoleBinding.rbac.authorization.k8s.io",
        "test-clusterrole5-test-org-user",
    )
    assert ri.get_desired(
        "test-cluster",
        NAMESPACE_CLUSTER_SCOPE,
        "ClusterRoleBinding.rbac.authorization.k8s.io",
        "test-clusterrole-access-test-org-user",
    )


def test_fetch_desired_state_v2_empty_clusters(mocker: MockerFixture) -> None:
    ri = ResourceInventory()
    ri.initialize_resource_type(
        "test-cluster5",
        NAMESPACE_CLUSTER_SCOPE,
        "ClusterRoleBinding.rbac.authorization.k8s.io",
    )
    mocker.patch(
        "reconcile.openshift_clusterrolebindings.get_app_interface_clusterroles"
    ).return_value = get_app_interface_test_clusterroles()
    fetch_desired_state_v2(ri, allowed_clusters=set())
    assert not ri.get_desired(
        "test-cluster5",
        NAMESPACE_CLUSTER_SCOPE,
        "ClusterRoleBinding.rbac.authorization.k8s.io",
        "test-clusterrole5-test-org-user",
    )
