from reconcile.gql_definitions.common.ocm_environments import (
    OCMEnvironment,
    query,
)
from reconcile.utils.gql import GqlApi


class NoOCMEnvironmentsFoundError(Exception):
    pass


def get_ocm_environments(
    gql_api: GqlApi,
    env_name: str | None = None,
) -> list[OCMEnvironment]:
    """Returns OCM Environments and raises err if none are found"""
    variables = {"name": env_name} if env_name else None
    data = query(query_func=gql_api.query, variables=variables)
    if not data.environments:
        raise NoOCMEnvironmentsFoundError(f"No OCM Environments found for {env_name=}")
    return data.environments
