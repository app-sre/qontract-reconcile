from reconcile.gql_definitions.common.ocm_environments import query
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.utils import gql


def get_ocm_environments() -> list[OCMEnvironment]:
    data = query(gql.get_api().query)
    return list(data.environments or [])
