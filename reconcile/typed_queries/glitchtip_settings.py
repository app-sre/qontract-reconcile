from reconcile.gql_definitions.glitchtip.glitchtip_settings import query
from reconcile.utils import gql


def get_glitchtip_settings(
    read_timeout: int = 30, max_retries: int = 3, mail_domain: str = "redhat.com"
) -> tuple[int, int, str]:
    """Returns Glitchtip Settings."""
    gqlapi = gql.get_api()
    if _s := query(query_func=gqlapi.query).settings:
        if _gs := _s[0].glitchtip:
            if _gs.read_timeout is not None:
                read_timeout = _gs.read_timeout
            if _gs.max_retries is not None:
                max_retries = _gs.max_retries
            if _gs.mail_domain is not None:
                mail_domain = _gs.mail_domain
    return read_timeout, max_retries, mail_domain
