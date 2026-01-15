from typing import Literal

IntegrationNameType = Literal["openshift-rolebindings", "openshift-clusterrolebindings"]

OPENSHIFT_ROLEBINDINGS_INTEGRATION_NAME = "openshift-rolebindings"
OPENSHIFT_CLUSTERROLEBINDINGS_INTEGRATION_NAME = "openshift-clusterrolebindings"

ROLE_BINDING_RESOURCE_KIND = "RoleBinding"
CLUSTER_ROLE_BINDING_RESOURCE_KIND = "ClusterRoleBinding"
ROLE_KIND = "Role"
CLUSTER_ROLE_KIND = "ClusterRole"
