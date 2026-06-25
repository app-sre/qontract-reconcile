from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from reconcile.gql_definitions.terraform_repo.terraform_repo import query

if TYPE_CHECKING:
    from reconcile.utils.gql import GqlApi


def get_tf_repo_inventory(gql: GqlApi) -> Counter:
    repos = query(gql.query).repos or []
    return Counter(r.account.name for r in repos)
