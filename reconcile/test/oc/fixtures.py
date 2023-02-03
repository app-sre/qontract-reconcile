from reconcile.gql_definitions.common.clusters import ClusterV1
from reconcile.gql_definitions.common.namespaces import NamespaceV1
from reconcile.test.fixtures import Fixtures

fxt = Fixtures("oc_connection_parameters")


def load_cluster_for_connection_parameters(path: str) -> ClusterV1:
    content = fxt.get_anymarkup(path)
    return ClusterV1(**content)


def load_namespace_for_connection_parameters(path: str) -> NamespaceV1:
    content = fxt.get_anymarkup(path)
    return NamespaceV1(**content)
