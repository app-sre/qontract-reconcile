from reconcile.gql_definitions.common.clusters import ClusterV1
from reconcile.gql_definitions.common.namespaces import NamespaceV1
from reconcile.test.fixtures import Fixtures
from reconcile.utils.models import data_default_none

fxt = Fixtures("oc_connection_parameters")


def load_cluster_for_connection_parameters(path: str) -> ClusterV1:
    content = fxt.get_anymarkup(path)
    data = data_default_none(ClusterV1, content)
    assert isinstance(data, dict)
    return ClusterV1(**data)


def load_namespace_for_connection_parameters(path: str) -> NamespaceV1:
    content = fxt.get_anymarkup(path)
    data = data_default_none(NamespaceV1, content)
    assert isinstance(data, dict)
    return NamespaceV1(**data)
