from typing import Literal

IntegrationNameType = Literal["openshift-rolebindings", "openshift-clusterrolebindings"]
OPENSHIFT_ROLEBINDINGS_INTEGRATION_NAME = "openshift-rolebindings"
OPENSHIFT_ROLEBINDINGS_INTEGRATION_RESOURCE_KIND = "RoleBinding"

OPENSHIFT_CLUSTERROLEBINDINGS_INTEGRATION_NAME = "openshift-clusterrolebindings"
OPENSHIFT_CLUSTERROLEBINDINGS_INTEGRATION_RESOURCE_KIND = "ClusterRoleBinding"
CLUSTER_ROLE_BINDING_RESOURCE_KIND = "ClusterRoleBinding"
ROLE_BINDING_RESOURCE_KIND = "RoleBinding"
ROLE_KIND = "Role"
CLUSTER_ROLE_KIND = "ClusterRole"
