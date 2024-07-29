from reconcile.gql_definitions.common.quay_instances import (
    QuayInstanceV1,
)
from reconcile.gql_definitions.common.quay_instances import (
    query as quay_instances_query,
)
from reconcile.gql_definitions.common.quay_orgs import (
    QuayOrgV1,
)
from reconcile.gql_definitions.common.quay_orgs import (
    query as quay_orgs_query,
)
from reconcile.utils import gql


def get_quay_instances() -> list[QuayInstanceV1]:
    data = quay_instances_query(gql.get_api().query)
    return list(data.instances or [])


def get_quay_orgs() -> list[QuayOrgV1]:
    data = quay_orgs_query(gql.get_api().query)
    return list(data.orgs or [])
