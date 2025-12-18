from collections.abc import Callable

from pydantic import BaseModel
from qontract_utils.vcs import Provider

from reconcile.gql_definitions.common.vcs import query
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils import gql


class Vcs(BaseModel):
    name: str
    url: str
    default: bool = False
    token: VaultSecret
    provider: Provider


def get_vcs_instances(query_func: Callable | None = None) -> list[Vcs]:
    if not query_func:
        query_func = gql.get_api().query
    data = query(query_func=query_func)
    vcs = [
        Vcs(
            name=gh_org.name,
            url=gh_org.url,
            default=gh_org.default or False,
            token=gh_org.token,
            provider=Provider.GITHUB,
        )
        for gh_org in data.gh_orgs or []
    ]
    vcs += [
        Vcs(
            name=gl_instance.name,
            url=gl_instance.url,
            token=gl_instance.token,
            provider=Provider.GITLAB,
        )
        for gl_instance in data.gl_instances or []
    ]
    return vcs
