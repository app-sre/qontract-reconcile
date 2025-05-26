import logging
from collections import defaultdict
from dataclasses import dataclass
from itertools import starmap

from reconcile import (
    mr_client_gateway,
)
from reconcile.gql_definitions.common.users_paths import UserV1
from reconcile.typed_queries.ldap_settings import get_ldap_settings
from reconcile.typed_queries.users_paths import get_users_paths
from reconcile.utils.defer import defer
from reconcile.utils.ldap_client import LdapClient
from reconcile.utils.mr import (
    CreateDeleteUserAppInterface,
    CreateDeleteUserInfra,
)
from reconcile.utils.mr.user_maintenance import PathSpec, PathTypes

QONTRACT_INTEGRATION = "ldap-users"


@dataclass
class UserPaths:
    username: str
    paths: list[PathSpec]


def transform_users_paths(users_paths: list[UserV1]) -> list[UserPaths]:
    users = defaultdict(list)
    for user in users_paths:
        u = user.org_username
        users[u].append(PathSpec(PathTypes.USER, "data" + user.path))
        for r in user.requests or []:
            users[u].append(PathSpec(PathTypes.REQUEST, "data" + r.path))
        for q in user.queries or []:
            users[u].append(PathSpec(PathTypes.QUERY, "data" + q.path))
        for g in user.gabi_instances or []:
            users[u].append(PathSpec(PathTypes.GABI, "data" + g.path))
        for a in user.aws_accounts or []:
            users[u].append(PathSpec(PathTypes.AWS_ACCOUNTS, "data" + a.path))
        for s in user.schedules or []:
            users[u].append(PathSpec(PathTypes.SCHEDULE, "data" + s.path))

    return list(starmap(UserPaths, users.items()))


@defer
def run(dry_run, app_interface_project_id, infra_project_id, defer=None):
    users = transform_users_paths(get_users_paths())
    ldap_settings = get_ldap_settings()

    with LdapClient.from_params(
        server_url=ldap_settings.server_url,
        user=None,
        password=None,
        base_dn=ldap_settings.base_dn,
    ) as ldap_client:
        ldap_users = ldap_client.get_users([u.username for u in users])

    users_to_delete = [u for u in users if u.username not in ldap_users]

    if not dry_run:
        mr_cli_app_interface = mr_client_gateway.init(
            gitlab_project_id=app_interface_project_id, sqs_or_gitlab="gitlab"
        )
        defer(mr_cli_app_interface.cleanup)
        mr_cli_infra = mr_client_gateway.init(
            gitlab_project_id=infra_project_id, sqs_or_gitlab="gitlab"
        )
        defer(mr_cli_infra.cleanup)

    for u in users_to_delete:
        username = u.username
        paths = u.paths
        logging.info(["delete_user", username])

        if not dry_run:
            mr = CreateDeleteUserAppInterface(username, paths)
            mr.submit(cli=mr_cli_app_interface)

    if not dry_run:
        usernames = [u.username for u in users_to_delete]
        mr_infra = CreateDeleteUserInfra(usernames)
        mr_infra.submit(cli=mr_cli_infra)
