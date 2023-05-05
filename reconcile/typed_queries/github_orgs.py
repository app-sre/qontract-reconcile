from reconcile.gql_definitions.common.github_orgs import (
    GithubOrgV1,
    query,
)
from reconcile.utils import gql


def get_github_orgs() -> list[GithubOrgV1]:
    gqlapi = gql.get_api()
    data = query(gqlapi.query)
    return list(data.orgs or [])
