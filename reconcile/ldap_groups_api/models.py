"""Desired-state helpers for ldap-groups-api (ported from legacy integration)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel
from qontract_utils.internal_groups_api.models import Entity, EntityType, Group

from reconcile.gql_definitions.ldap_groups.roles import RoleV1
from reconcile.gql_definitions.ldap_groups.roles import query as roles_query
from reconcile.gql_definitions.ldap_groups.settings import LdapGroupsSettingsV1
from reconcile.gql_definitions.ldap_groups.settings import query as settings_query
from reconcile.utils.disabled_integrations import (
    HasDisableIntegrations,
    disabled_integrations,
)
from reconcile.utils.exceptions import (
    AppInterfaceLdapGroupsSettingsError,
    AppInterfaceSettingsError,
)
from reconcile.utils.helpers import find_duplicates
from reconcile.utils.membershipsources.validation import (
    CircularMembershipError,
    find_circular_memberships,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

QONTRACT_INTEGRATION = "ldap-groups-api"


def get_integration_settings(query_func: Callable) -> LdapGroupsSettingsV1:
    data = settings_query(query_func)
    if not data.settings:
        raise AppInterfaceSettingsError("No app-interface settings found.")
    if not data.settings[0].ldap_groups:
        raise AppInterfaceLdapGroupsSettingsError(
            "No app-interface ldap-groups settings found."
        )
    return data.settings[0].ldap_groups


def get_roles(query_func: Callable) -> list[RoleV1]:
    data = roles_query(query_func, variables={})
    roles = list(data.roles or [])
    if duplicates := find_duplicates(
        role.ldap_group.name for role in roles if role.ldap_group
    ):
        for dup in duplicates:
            logging.error(f"{dup} is already in use by another role.")
        raise ValueError("Duplicate ldapGroup value(s) found.")
    return roles


def validate_no_circular_memberships(
    roles: Iterable[RoleV1], desired_groups: Iterable[Group]
) -> None:
    if conflicts := find_circular_memberships(
        roles, published_ldap_groups=(g.name for g in desired_groups)
    ):
        conflict_desc = ", ".join(
            f"role '{role}' reads group '{group}'" for role, group in conflicts
        )
        raise CircularMembershipError(
            "Circular membership dependency detected: a role's memberSources "
            "cannot reference a group that ldap-groups also publishes to "
            f"(via another role's ldapGroup): {conflict_desc}"
        )


class LdapGroupMember(BaseModel, extra="ignore"):
    """Minimal member shape for resolve_role_members output.

    memberSources-resolved members only populate org_username, so every
    other field must be optional.
    """

    org_username: str


def get_desired_groups_for_roles(
    roles: Iterable[RoleV1],
    default_owners: list[Entity],
    contact_list: str,
    resolved_members: Mapping[str, list[LdapGroupMember]] | None = None,
) -> list[Group]:
    groups: list[Group] = []
    for role in roles:
        if not role.ldap_group:
            continue
        if resolved_members is not None:
            role_members = resolved_members.get(role.name, [])
        else:
            role_members = [
                LdapGroupMember(org_username=u.org_username) for u in role.users
            ]
        members = [
            Entity(type=EntityType.USER, id=m.org_username) for m in role_members
        ]
        groups.append(
            Group(
                name=role.ldap_group.name,
                description="Persisted App-Interface role. Managed by qontract-reconcile",
                notes=role.ldap_group.notes,
                display_name=f"{role.ldap_group.name} (App-Interface))",
                members=members,
                owners=default_owners
                if not role.ldap_group.members_are_owners
                else default_owners + members,
                contact_list=contact_list,
            )
        )
    return groups


# Both names during ldap-groups → ldap-groups-api cutover (disable.integrations).
_LDAP_GROUPS_AWS_DISABLE_NAMES = frozenset({"ldap-groups", "ldap-groups-api"})


class AccountSSO(HasDisableIntegrations, Protocol):
    name: str
    uid: str
    sso: bool | None


def ldap_groups_aws_integration_enabled(
    disable_obj: Mapping[str, Any] | HasDisableIntegrations | None,
) -> bool:
    disabled = set(disabled_integrations(disable_obj))
    return not disabled.intersection(_LDAP_GROUPS_AWS_DISABLE_NAMES)


def unique_sso_aws_accounts_for_ldap_groups(
    accounts: Iterable[AccountSSO], account_name: str | None = None
) -> list[AccountSSO]:
    """Unique SSO AWS accounts eligible for ldap-groups rover group generation."""
    filtered_account: dict[str, AccountSSO] = {}
    for account in accounts:
        if account_name and account.name != account_name:
            continue
        if not account.sso:
            continue
        if not ldap_groups_aws_integration_enabled(account):
            continue
        if account.uid in filtered_account:
            continue
        filtered_account[account.uid] = account
    return list(filtered_account.values())


def get_desired_groups_for_aws_roles(
    roles: Iterable[RoleV1],
    default_owners: Iterable[Entity],
    contact_list: str,
    aws_sso_namespace: str,
) -> list[Group]:
    groups: list[Group] = []
    for role in roles:
        if not role.users or (not role.aws_groups and not role.user_policies):
            continue
        user_policies = role.user_policies or []
        aws_groups = role.aws_groups or []
        for account in unique_sso_aws_accounts_for_ldap_groups(
            accounts=[i.account for i in user_policies + aws_groups],
        ):
            group_name = f"{aws_sso_namespace}-{account.uid}-{role.name}"
            groups.append(
                Group(
                    name=group_name,
                    description=(
                        f"AWS account: '{account.name}' Role: '{role.name}' "
                        "Managed by qontract-reconcile"
                    ),
                    display_name=group_name,
                    members=[
                        Entity(type=EntityType.USER, id=user.org_username)
                        for user in role.users
                    ],
                    owners=list(default_owners),
                    contact_list=contact_list,
                )
            )
    return groups
