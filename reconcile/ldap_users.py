import logging
from collections.abc import Callable

from pydantic import BaseModel, Field

from reconcile import (
    mr_client_gateway,
)
from reconcile.gql_definitions.common.ldap_settings import LdapSettingsV1
from reconcile.gql_definitions.common.users_with_paths import UserV1
from reconcile.typed_queries.ldap_settings import get_ldap_settings
from reconcile.typed_queries.users_with_paths import get_users_with_paths
from reconcile.utils.defer import defer
from reconcile.utils.ldap_client import LdapClient
from reconcile.utils.mr import (
    CreateDeleteUserAppInterface,
    CreateDeleteUserInfra,
)
from reconcile.utils.mr.user_maintenance import PathSpec, PathTypes

QONTRACT_INTEGRATION = "ldap-users"


class UserPaths(BaseModel):
    username: str
    paths: list[PathSpec] = Field(default_factory=list)


def transform_users_with_paths(users_with_paths: list[UserV1]) -> list[UserPaths]:
    """Converts UserV1 objects into UserPaths, consolidating all associated resource paths by type."""

    users_paths = []
    for user in users_with_paths:
        up = UserPaths(username=user.org_username)
        up.paths.append(PathSpec(type=PathTypes.USER, path=user.path))
        for r in user.requests or []:
            up.paths.append(PathSpec(type=PathTypes.REQUEST, path=r.path))
        for q in user.queries or []:
            up.paths.append(PathSpec(type=PathTypes.QUERY, path=q.path))
        for g in user.gabi_instances or []:
            up.paths.append(PathSpec(type=PathTypes.GABI, path=g.path))
        for a in user.aws_accounts or []:
            up.paths.append(PathSpec(type=PathTypes.AWS_ACCOUNTS, path=a.path))
        for s in user.schedules or []:
            up.paths.append(PathSpec(type=PathTypes.SCHEDULE, path=s.path))

        users_paths.append(up)

    return users_paths


def get_usernames(users_paths: list[UserPaths]) -> list[str]:
    """Extracts a list of usernames from a list of UserPaths objects."""
    return [u.username for u in users_paths]


def filter_users_not_exists(
    users_paths: list[UserPaths], ldap_users: set[str]
) -> list[UserPaths]:
    """Filters out UserPaths objects whose usernames are not present in the given set of LDAP users."""

    return [u for u in users_paths if u.username not in ldap_users]


def get_ldap_users(ldap_settings: LdapSettingsV1, usernames: list[str]) -> set[str]:
    """Retrieves existing usernames from LDAP based on the provided list and connection settings."""
    with LdapClient.from_params(
        server_url=ldap_settings.server_url,
        user=None,
        password=None,
        base_dn=ldap_settings.base_dn,
    ) as ldap_client:
        return ldap_client.get_users(usernames)


@defer
def delete_user_from_app_interface(
    dry_run: bool,
    app_interface_project_id: str | int | None,
    users: list[UserPaths],
    defer: Callable | None = None,
) -> None:
    """Delete user data stored in the repository app-interface related with the given users."""
    if not dry_run:
        mr_cli_app_interface = mr_client_gateway.init(
            gitlab_project_id=app_interface_project_id, sqs_or_gitlab="gitlab"
        )
        if defer:
            defer(mr_cli_app_interface.cleanup)

    for user in users:
        logging.info(["delete_user", user.username])

        if not dry_run:
            mr = CreateDeleteUserAppInterface(user.username, user.paths)
            mr.submit(cli=mr_cli_app_interface)


def delete_user_from_infra(
    dry_run: bool,
    infra_project_id: str | int | None,
    usernames: list[str],
) -> None:
    """Delete user data stored in the repository infra related with the given usernames."""
    if not dry_run:
        with mr_client_gateway.init(
            gitlab_project_id=infra_project_id, sqs_or_gitlab="gitlab"
        ) as mr_cli_infra:
            mr_infra = CreateDeleteUserInfra(usernames)
            mr_infra.submit(cli=mr_cli_infra)


def run(dry_run: bool, app_interface_project_id: str, infra_project_id: str) -> None:
    """
    Synchronizes user data stored in the repositories app_interface and infra
    associated with users that are no longer found in the LDAP.
    """
    users_paths = transform_users_with_paths(get_users_with_paths())

    ldap_users = get_ldap_users(get_ldap_settings(), get_usernames(users_paths))

    users_to_delete = filter_users_not_exists(users_paths, ldap_users)
    usernames_to_delete = get_usernames(users_to_delete)

    delete_user_from_app_interface(dry_run, app_interface_project_id, users_to_delete)
    delete_user_from_infra(dry_run, infra_project_id, usernames_to_delete)
