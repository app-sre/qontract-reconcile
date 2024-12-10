from collections import Counter

from reconcile.gql_definitions.terraform_repo.terraform_repo import query
from reconcile.utils.gql import GqlApi


def get_tf_repo_inventory(gql: GqlApi) -> Counter:
    repos = query(gql.query).repos or []
    return Counter(r.account.name for r in repos)
